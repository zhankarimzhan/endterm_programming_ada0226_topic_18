-- Представления: то, что не хранится, а вычисляется из запросов, кандидатов и отзывов.

-- Ответ каждого метода на каждый запрос.
-- found   — оценка лучшего кандидата не ниже порога метода;
-- helpful — засчитан ли ответ методу:
--   есть отзыв на этот ответ -> он;
--   отзыва на этот ответ нет, но пользователь одобрил другой ответ на этот же запрос -> false;
--   иначе NULL (не оценён).
CREATE OR REPLACE VIEW v_method_answers AS
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
       COALESCE(c.score >= m.min_score, false)   AS found,
       CASE
           WHEN NOT COALESCE(c.score >= m.min_score, false) THEN NULL
           WHEN f.helpful IS NOT NULL THEN f.helpful
           WHEN EXISTS (SELECT 1 FROM feedback f2
                        WHERE f2.request_id = r.request_id AND f2.helpful) THEN false
       END                                       AS helpful
FROM method_runs mr
JOIN requests r      ON r.request_id = mr.request_id
JOIN methods m       ON m.method_id = mr.method_id
LEFT JOIN candidates c ON c.request_id = mr.request_id AND c.method_id = mr.method_id AND c.rank = 1
LEFT JOIN feedback f   ON f.request_id = mr.request_id AND f.faq_id = c.faq_id;

-- Вопросы без подходящего ответа (кандидаты для пополнения FAQ):
--   not_found  — ни один метод не нашёл ответ выше порога;
--   bad_answer — все найденные ответы пользователь отклонил (👎) и ни один не одобрил.
-- best_faq_id / best_score — ближайший кандидат (максимум оценки относительно порога метода).
CREATE OR REPLACE VIEW v_unanswered AS
WITH per_request AS (
    SELECT request_id, query_text, asked_at,
           BOOL_OR(found)                                       AS any_found,
           COALESCE(BOOL_OR(helpful), false)                    AS any_helpful,
           COUNT(*) FILTER (WHERE found)                        AS found_cnt,
           COUNT(*) FILTER (WHERE found AND helpful = false)    AS rejected_cnt
    FROM v_method_answers
    GROUP BY request_id, query_text, asked_at
)
SELECT p.request_id,
       p.query_text,
       p.asked_at,
       CASE WHEN NOT p.any_found THEN 'not_found' ELSE 'bad_answer' END AS reason,
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
WHERE (NOT p.any_found OR (p.found_cnt = p.rejected_cnt AND NOT p.any_helpful))
  AND NOT EXISTS (SELECT 1 FROM resolutions s WHERE s.request_id = p.request_id);
