-- Представления: то, что не хранится, а вычисляется из запросов, кандидатов и прогонов на тестовых вопросах.

-- Пересоздаются целиком: при изменении набора колонок CREATE OR REPLACE не работает
DROP VIEW IF EXISTS v_unanswered;
DROP VIEW IF EXISTS v_method_answers;

-- Ответ каждого метода на каждый запрос.
-- found — оценка лучшего кандидата не ниже порога метода.
CREATE VIEW v_method_answers AS
SELECT r.request_id,
       r.query_text,
       r.mode,
       r.asked_at,
       m.method_id,
       m.name                                    AS method,
       m.title,
       mr.latency_ms,
       c.faq_id                                  AS best_faq_id,
       c.score,
       COALESCE(c.score >= m.min_score, false)   AS found
FROM method_runs mr
JOIN requests r      ON r.request_id = mr.request_id
JOIN methods m       ON m.method_id = mr.method_id
LEFT JOIN candidates c ON c.request_id = mr.request_id AND c.method_id = mr.method_id AND c.rank = 1;

-- Вопросы без ответа (кандидаты для пополнения FAQ): ни один метод не нашёл ответ выше порога.
-- best_faq_id / best_score — ближайший кандидат (максимум оценки относительно порога метода).
CREATE VIEW v_unanswered AS
WITH per_request AS (
    SELECT request_id, query_text, asked_at
    FROM v_method_answers
    GROUP BY request_id, query_text, asked_at
    HAVING NOT BOOL_OR(found)
)
SELECT p.request_id,
       p.query_text,
       p.asked_at,
       best.faq_id AS best_faq_id,
       best.score  AS best_score
FROM per_request p
LEFT JOIN LATERAL (
    SELECT c.faq_id, c.score
    FROM candidates c JOIN methods m ON m.method_id = c.method_id
    WHERE c.request_id = p.request_id AND c.rank = 1
    ORDER BY c.score / NULLIF(m.min_score, 0) DESC
    LIMIT 1
) best ON true
WHERE NOT EXISTS (SELECT 1 FROM resolutions s WHERE s.request_id = p.request_id);

-- Результат последнего прогона каждого метода на каждом тестовом вопросе:
-- first_rank — место первого допустимого ответа в топ-k (NULL — не нашёл),
-- confident_wrong — ответ неверный, но сходство выше порога метода (бот выдал бы его как найденный).
CREATE OR REPLACE VIEW v_test_hits AS
WITH last_runs AS (
    SELECT DISTINCT ON (method_id, test_set) run_id, method_id, test_set
    FROM runs
    ORDER BY method_id, test_set, created_at DESC
)
SELECT lr.run_id,
       lr.test_set,
       m.method_id,
       m.title                                                 AS method,
       m.preprocessing,
       q.query_id,
       q.text                                                  AS query_text,
       q.query_type,
       q.topic,
       MIN(p.rank) FILTER (WHERE a.faq_id IS NOT NULL)         AS first_rank,
       MAX(p.faq_id) FILTER (WHERE p.rank = 1)                 AS top_faq_id,
       MAX(p.score) FILTER (WHERE p.rank = 1)                  AS top_score,
       COALESCE(MAX(p.score) FILTER (WHERE p.rank = 1) >= m.min_score
                AND MIN(p.rank) FILTER (WHERE a.faq_id IS NOT NULL) IS DISTINCT FROM 1, false) AS confident_wrong
FROM last_runs lr
JOIN methods m          ON m.method_id = lr.method_id
JOIN predictions p      ON p.run_id = lr.run_id
JOIN test_queries q     ON q.query_id = p.query_id
LEFT JOIN test_acceptable a ON a.query_id = p.query_id AND a.faq_id = p.faq_id
GROUP BY lr.run_id, lr.test_set, m.method_id, m.title, m.preprocessing, m.min_score,
         q.query_id, q.text, q.query_type, q.topic;
