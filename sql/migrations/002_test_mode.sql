-- Режим 'test' для запросов: тестовые вопросы (data/test_queries.csv), которые init_project.py
-- прогоняет через все методы при первичном запуске проекта.
-- Запуск: docker exec -i faq-postgres psql -v ON_ERROR_STOP=1 -U faq -d faq_db < sql/migrations/002_test_mode.sql

ALTER TABLE requests DROP CONSTRAINT IF EXISTS requests_mode_check;
ALTER TABLE requests ADD CONSTRAINT requests_mode_check CHECK (mode IN ('compare', 'single', 'test'));
