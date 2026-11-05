-- Отзывы 👍/👎 больше не используются: качество методов меряется только на тестовых вопросах
-- (runs, predictions, v_test_hits). Таблица feedback не удаляется — собранные отзывы остаются в базе.
-- Тестовые вопросы больше не пишутся в статистику бота (режим 'test'): их запросы удаляются.
-- Запуск: docker exec -i faq-postgres psql -v ON_ERROR_STOP=1 -U faq -d faq_db < sql/migrations/004_drop_feedback.sql
-- затем: docker exec -i faq-postgres psql -v ON_ERROR_STOP=1 -U faq -d faq_db < sql/init/03_views.sql

BEGIN;

DELETE FROM requests WHERE mode = 'test';
ALTER TABLE requests DROP CONSTRAINT IF EXISTS requests_mode_check;
ALTER TABLE requests ADD CONSTRAINT requests_mode_check CHECK (mode IN ('compare', 'single'));

COMMENT ON TABLE feedback IS 'Не используется с миграции 004: отзывы 👍/👎 убраны из бота и статистики';

COMMIT;
