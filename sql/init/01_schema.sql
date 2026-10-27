-- Схема базы FAQ-чат-бота (3НФ).
-- Выполняется автоматически при первом запуске контейнера (пустой том pgdata).
-- Для уже работающей базы со старой схемой — sql/migrations/001_normalize.sql.

-- ---------- Корпус FAQ ----------

CREATE TABLE categories (
    category_id   SERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE
);

CREATE TABLE faq (
    faq_id        INTEGER PRIMARY KEY,
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL,
    raw_label     TEXT,                                   -- исходная метка из датасета
    category_id   INTEGER REFERENCES categories (category_id)
);

-- Обратный индекс: стеммы слов вопросов FAQ (после предобработки) и их частота в вопросе
CREATE TABLE terms (
    term_id       SERIAL PRIMARY KEY,
    term          TEXT NOT NULL UNIQUE
);

CREATE TABLE faq_terms (
    faq_id        INTEGER NOT NULL REFERENCES faq (faq_id) ON DELETE CASCADE,
    term_id       INTEGER NOT NULL REFERENCES terms (term_id) ON DELETE CASCADE,
    tf            SMALLINT NOT NULL CHECK (tf > 0),        -- сколько раз стемм встречается в вопросе
    PRIMARY KEY (faq_id, term_id)
);

-- ---------- Методы поиска ----------

CREATE TABLE methods (
    method_id     SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,                          -- rule_based / bow / tfidf / embeddings / pg_trgm
    preprocessing TEXT NOT NULL DEFAULT 'none',           -- none / lower / stem / lemma
    title         TEXT,
    min_score     REAL,                                   -- порог: ниже него ответ считается ненайденным
    fit_seconds   REAL,                                   -- время подготовки индекса
    memory_mb     REAL,                                   -- память индекса
    updated_at    TIMESTAMP,
    UNIQUE (name, preprocessing)
);

-- ---------- Работа бота ----------

-- Вопрос пользователя (без данных о пользователе)
CREATE TABLE requests (
    request_id    UUID PRIMARY KEY,
    query_text    TEXT NOT NULL,
    mode          TEXT NOT NULL CHECK (mode IN ('compare', 'single')),   -- все методы или один
    asked_at      TIMESTAMP NOT NULL DEFAULT now()
);

-- Запуск метода на запросе
CREATE TABLE method_runs (
    request_id    UUID NOT NULL REFERENCES requests (request_id) ON DELETE CASCADE,
    method_id     INTEGER NOT NULL REFERENCES methods (method_id),
    latency_ms    REAL,                                   -- время поиска
    PRIMARY KEY (request_id, method_id)
);

-- Топ-k вопросов FAQ, найденных методом (rank 1 — ответ метода)
CREATE TABLE candidates (
    request_id    UUID NOT NULL,
    method_id     INTEGER NOT NULL,
    rank          SMALLINT NOT NULL CHECK (rank BETWEEN 1 AND 10),
    faq_id        INTEGER NOT NULL REFERENCES faq (faq_id) ON DELETE CASCADE,
    score         REAL NOT NULL,
    PRIMARY KEY (request_id, method_id, rank),
    FOREIGN KEY (request_id, method_id) REFERENCES method_runs (request_id, method_id) ON DELETE CASCADE
);

-- Оценка пользователя: подошёл ли ответ faq_id на запрос. К методу не привязана —
-- засчитывается ли метод, вычисляется (см. представление v_method_answers).
CREATE TABLE feedback (
    request_id    UUID NOT NULL REFERENCES requests (request_id) ON DELETE CASCADE,
    faq_id        INTEGER NOT NULL REFERENCES faq (faq_id) ON DELETE CASCADE,
    helpful       BOOLEAN NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (request_id, faq_id)
);

-- Вопрос без ответа обработан (ответ добавлен в FAQ)
CREATE TABLE resolutions (
    request_id    UUID PRIMARY KEY REFERENCES requests (request_id) ON DELETE CASCADE,
    resolved_at   TIMESTAMP NOT NULL DEFAULT now()
);

-- ---------- Оценка методов на тестовых вопросах ----------

CREATE TABLE test_queries (
    query_id      SERIAL PRIMARY KEY,
    text          TEXT NOT NULL,
    true_faq_id   INTEGER NOT NULL REFERENCES faq (faq_id)
);

CREATE TABLE runs (
    run_id        SERIAL PRIMARY KEY,
    method_id     INTEGER NOT NULL REFERENCES methods (method_id),
    p_at_1        NUMERIC(5, 4),
    p_at_3        NUMERIC(5, 4),
    mrr           NUMERIC(5, 4),
    time_ms       NUMERIC(10, 3),                         -- среднее время на запрос
    memory_mb     NUMERIC(10, 3),                         -- размер индекса
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE predictions (
    run_id        INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    query_id      INTEGER NOT NULL REFERENCES test_queries (query_id),
    rank          SMALLINT NOT NULL CHECK (rank BETWEEN 1 AND 10),
    faq_id        INTEGER NOT NULL REFERENCES faq (faq_id),
    score         REAL NOT NULL,
    PRIMARY KEY (run_id, query_id, rank)
);

CREATE INDEX idx_faq_category       ON faq (category_id);
CREATE INDEX idx_faq_terms_term     ON faq_terms (term_id);
CREATE INDEX idx_requests_asked     ON requests (asked_at);
CREATE INDEX idx_method_runs_method ON method_runs (method_id);
CREATE INDEX idx_candidates_faq     ON candidates (faq_id);
CREATE INDEX idx_predictions_query  ON predictions (query_id);
CREATE INDEX idx_runs_method        ON runs (method_id);
