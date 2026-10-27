-- Схема базы FAQ-чат-бота (3НФ).
-- Выполняется автоматически при первом запуске контейнера (пустой том pgdata).

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

CREATE TABLE test_queries (
    query_id      SERIAL PRIMARY KEY,
    text          TEXT NOT NULL,
    true_faq_id   INTEGER NOT NULL REFERENCES faq (faq_id)
);

CREATE TABLE methods (
    method_id     SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,                          -- baseline / bow / tfidf / embeddings
    preprocessing TEXT NOT NULL DEFAULT 'none',           -- none / stem / lemma
    UNIQUE (name, preprocessing)
);

-- Один запуск оценки метода на тестовых вопросах
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

-- Топ-k ответов метода на каждый тестовый вопрос
CREATE TABLE predictions (
    run_id        INTEGER NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    query_id      INTEGER NOT NULL REFERENCES test_queries (query_id),
    rank          SMALLINT NOT NULL CHECK (rank BETWEEN 1 AND 10),
    faq_id        INTEGER NOT NULL REFERENCES faq (faq_id),
    score         REAL NOT NULL,
    PRIMARY KEY (run_id, query_id, rank)
);

-- История вопросов пользователя из консольного меню
CREATE TABLE chat_log (
    log_id        SERIAL PRIMARY KEY,
    user_query    TEXT NOT NULL,
    method_id     INTEGER REFERENCES methods (method_id),
    faq_id        INTEGER REFERENCES faq (faq_id),
    score         REAL,
    asked_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_faq_category      ON faq (category_id);
CREATE INDEX idx_predictions_query ON predictions (query_id);
CREATE INDEX idx_runs_method       ON runs (method_id);
