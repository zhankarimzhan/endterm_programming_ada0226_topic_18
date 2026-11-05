-- Наборы тестовых вопросов: base (data/test_queries.csv) и paraphrases (data/paraphrases.csv —
-- разные формулировки 10 вопросов: сленг, синонимы, опечатки, транслит, английский, зеркальные).
-- Тип формулировки и тема — для разбивки метрик; допустимые ответы — отдельная таблица
-- (у вопроса может быть несколько верных ответов FAQ, например дубликаты).
-- Запуск: docker exec -i faq-postgres psql -v ON_ERROR_STOP=1 -U faq -d faq_db < sql/migrations/003_test_sets.sql
-- После миграции: python -m analytics.evaluation --force

BEGIN;

ALTER TABLE test_queries ADD COLUMN IF NOT EXISTS test_set   TEXT NOT NULL DEFAULT 'base';
ALTER TABLE test_queries ADD COLUMN IF NOT EXISTS query_type TEXT;
ALTER TABLE test_queries ADD COLUMN IF NOT EXISTS topic      TEXT;

CREATE TABLE IF NOT EXISTS test_acceptable (
    query_id      INTEGER NOT NULL REFERENCES test_queries (query_id) ON DELETE CASCADE,
    faq_id        INTEGER NOT NULL REFERENCES faq (faq_id) ON DELETE CASCADE,
    PRIMARY KEY (query_id, faq_id)
);

ALTER TABLE runs ADD COLUMN IF NOT EXISTS test_set TEXT NOT NULL DEFAULT 'base';

COMMIT;
