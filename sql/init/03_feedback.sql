-- Отзывы пользователей и вопросы, на которые бот не смог ответить.

-- Отзыв на ответ: true — 👍 подошёл, false — 👎 не подошёл, NULL — отзыва нет
ALTER TABLE chat_log ADD COLUMN IF NOT EXISTS helpful BOOLEAN;

-- Вопросы без подходящего ответа: материал для пополнения FAQ
CREATE TABLE IF NOT EXISTS unanswered_questions (
    id            SERIAL PRIMARY KEY,
    log_id        INTEGER UNIQUE REFERENCES chat_log (log_id) ON DELETE CASCADE,
    user_query    TEXT NOT NULL,
    method_id     INTEGER REFERENCES methods (method_id),
    best_faq_id   INTEGER REFERENCES faq (faq_id),     -- лучший найденный кандидат (даже если ниже порога)
    best_score    REAL,
    reason        TEXT NOT NULL CHECK (reason IN ('not_found', 'bad_answer')),
    resolved      BOOLEAN NOT NULL DEFAULT false,     -- отметка, что ответ добавлен в FAQ
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);
