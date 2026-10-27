-- Миграция работающей базы со старой схемы (chat_log, unanswered_questions) на нормализованную:
-- requests, method_runs, candidates, feedback, resolutions, terms, faq_terms + представления.
-- Запуск: docker exec -i faq-postgres psql -v ON_ERROR_STOP=1 -U faq -d faq_db < sql/migrations/001_normalize.sql
-- Выполняется одной транзакцией: при ошибке база остаётся как была.

BEGIN;

ALTER TABLE methods ADD COLUMN IF NOT EXISTS title       TEXT;
ALTER TABLE methods ADD COLUMN IF NOT EXISTS min_score   REAL;
ALTER TABLE methods ADD COLUMN IF NOT EXISTS fit_seconds REAL;
ALTER TABLE methods ADD COLUMN IF NOT EXISTS memory_mb   REAL;
ALTER TABLE methods ADD COLUMN IF NOT EXISTS updated_at  TIMESTAMP;

-- Пороги методов (до перезапуска бота, который их тоже записывает)
UPDATE methods SET min_score = CASE name WHEN 'rule_based' THEN 0.15 WHEN 'embeddings' THEN 0.5 ELSE 0.3 END
WHERE min_score IS NULL;

CREATE TABLE IF NOT EXISTS terms (
    term_id SERIAL PRIMARY KEY,
    term    TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS faq_terms (
    faq_id  INTEGER NOT NULL REFERENCES faq (faq_id) ON DELETE CASCADE,
    term_id INTEGER NOT NULL REFERENCES terms (term_id) ON DELETE CASCADE,
    tf      SMALLINT NOT NULL CHECK (tf > 0),
    PRIMARY KEY (faq_id, term_id)
);
CREATE TABLE IF NOT EXISTS requests (
    request_id UUID PRIMARY KEY,
    query_text TEXT NOT NULL,
    mode       TEXT NOT NULL CHECK (mode IN ('compare', 'single')),
    asked_at   TIMESTAMP NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS method_runs (
    request_id UUID NOT NULL REFERENCES requests (request_id) ON DELETE CASCADE,
    method_id  INTEGER NOT NULL REFERENCES methods (method_id),
    latency_ms REAL,
    PRIMARY KEY (request_id, method_id)
);
CREATE TABLE IF NOT EXISTS candidates (
    request_id UUID NOT NULL,
    method_id  INTEGER NOT NULL,
    rank       SMALLINT NOT NULL CHECK (rank BETWEEN 1 AND 10),
    faq_id     INTEGER NOT NULL REFERENCES faq (faq_id) ON DELETE CASCADE,
    score      REAL NOT NULL,
    PRIMARY KEY (request_id, method_id, rank),
    FOREIGN KEY (request_id, method_id) REFERENCES method_runs (request_id, method_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS feedback (
    request_id UUID NOT NULL REFERENCES requests (request_id) ON DELETE CASCADE,
    faq_id     INTEGER NOT NULL REFERENCES faq (faq_id) ON DELETE CASCADE,
    helpful    BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (request_id, faq_id)
);
CREATE TABLE IF NOT EXISTS resolutions (
    request_id  UUID PRIMARY KEY REFERENCES requests (request_id) ON DELETE CASCADE,
    resolved_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Перенос данных из chat_log. У строк одиночного режима request_id не было — строим из log_id.
CREATE TEMP TABLE old_log AS
SELECT log_id, user_query, method_id, faq_id, score, helpful, latency_ms, asked_at,
       COALESCE(request_id, md5('log' || log_id)::uuid) AS rid,
       CASE WHEN request_id IS NULL THEN 'single' ELSE 'compare' END AS mode
FROM chat_log;

INSERT INTO requests (request_id, query_text, mode, asked_at)
SELECT rid, MIN(user_query), MIN(mode), MIN(asked_at) FROM old_log GROUP BY rid
ON CONFLICT DO NOTHING;

INSERT INTO method_runs (request_id, method_id, latency_ms)
SELECT rid, method_id, MAX(latency_ms) FROM old_log WHERE method_id IS NOT NULL GROUP BY rid, method_id
ON CONFLICT DO NOTHING;

-- В старой схеме ответ, не прошедший порог, не сохранялся (faq_id = NULL) — такие строки без кандидата
INSERT INTO candidates (request_id, method_id, rank, faq_id, score)
SELECT rid, method_id, 1, faq_id, score FROM old_log
WHERE method_id IS NOT NULL AND faq_id IS NOT NULL AND score IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO feedback (request_id, faq_id, helpful, created_at)
SELECT rid, faq_id, BOOL_OR(helpful), MIN(asked_at) FROM old_log
WHERE helpful IS NOT NULL AND faq_id IS NOT NULL GROUP BY rid, faq_id
ON CONFLICT DO NOTHING;

INSERT INTO resolutions (request_id, resolved_at)
SELECT DISTINCT o.rid, now() FROM unanswered_questions u JOIN old_log o ON o.log_id = u.log_id
WHERE u.resolved
ON CONFLICT DO NOTHING;

DROP TABLE unanswered_questions;
DROP TABLE chat_log;

CREATE INDEX IF NOT EXISTS idx_faq_terms_term     ON faq_terms (term_id);
CREATE INDEX IF NOT EXISTS idx_requests_asked     ON requests (asked_at);
CREATE INDEX IF NOT EXISTS idx_method_runs_method ON method_runs (method_id);
CREATE INDEX IF NOT EXISTS idx_candidates_faq     ON candidates (faq_id);

COMMIT;

-- После миграции создать представления: sql/init/03_views.sql
