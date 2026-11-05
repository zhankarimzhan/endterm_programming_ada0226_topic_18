-- Аналитические SQL-запросы проекта (PostgreSQL).
-- Формат: строка «-- name: <ключ> | <описание>» начинает запрос; queries_runner.py читает файл,
-- выполняет запросы и загружает результаты в pandas (они же — вкладка «SQL» в дашборде).
-- Используемые конструкции указаны в квадратных скобках.

-- name: labels_with_many_questions | Исходные метки датасета, у которых не меньше 5 вопросов [GROUP BY, HAVING]
SELECT raw_label,
       COUNT(*)                         AS questions,
       ROUND(AVG(length(question)))     AS avg_question_len
FROM faq
GROUP BY raw_label
HAVING COUNT(*) >= 5
ORDER BY questions DESC;

-- name: frequent_terms | Самые распространённые стеммы в вопросах FAQ (документная частота ≥ 20) [JOIN, GROUP BY, HAVING]
SELECT t.term,
       COUNT(*)      AS df,                 -- в скольких вопросах встречается
       SUM(ft.tf)    AS total_occurrences
FROM faq_terms ft
JOIN terms t ON t.term_id = ft.term_id
GROUP BY t.term
HAVING COUNT(*) >= 20
ORDER BY df DESC;

-- name: tfidf_keywords | Ключевые слова вопросов: топ-3 стемма по TF-IDF для каждой из крупных меток [CTE, JOIN, оконные ROW_NUMBER, подзапрос]
WITH n_docs AS (
    SELECT COUNT(*)::numeric AS n FROM faq
),
idf AS (
    SELECT term_id, ln((SELECT n FROM n_docs) / COUNT(*)) AS idf
    FROM faq_terms
    GROUP BY term_id
),
label_terms AS (
    SELECT f.raw_label, t.term, SUM(ft.tf * i.idf) AS tfidf
    FROM faq_terms ft
    JOIN faq f   ON f.faq_id = ft.faq_id
    JOIN terms t ON t.term_id = ft.term_id
    JOIN idf i   ON i.term_id = ft.term_id
    WHERE f.raw_label IN (SELECT raw_label FROM faq GROUP BY raw_label HAVING COUNT(*) >= 5)
    GROUP BY f.raw_label, t.term
),
ranked AS (
    SELECT raw_label, term, ROUND(tfidf::numeric, 2) AS tfidf,
           ROW_NUMBER() OVER (PARTITION BY raw_label ORDER BY tfidf DESC) AS rn
    FROM label_terms
)
SELECT raw_label, term, tfidf, rn AS place
FROM ranked
WHERE rn <= 3
ORDER BY raw_label, rn;

-- name: near_duplicate_questions | Пары вопросов FAQ с почти одинаковым набором слов (возможные дубликаты) [self-JOIN, CTE, GROUP BY, HAVING]
WITH sizes AS (
    SELECT faq_id, COUNT(*) AS n_terms FROM faq_terms GROUP BY faq_id
)
SELECT a.faq_id AS faq_a, b.faq_id AS faq_b,
       COUNT(*)                                                  AS shared_terms,
       ROUND(COUNT(*)::numeric / (sa.n_terms + sb.n_terms - COUNT(*)), 2) AS jaccard,
       fa.question AS question_a, fb.question AS question_b
FROM faq_terms a
JOIN faq_terms b ON b.term_id = a.term_id AND b.faq_id > a.faq_id
JOIN sizes sa ON sa.faq_id = a.faq_id
JOIN sizes sb ON sb.faq_id = b.faq_id
JOIN faq fa ON fa.faq_id = a.faq_id
JOIN faq fb ON fb.faq_id = b.faq_id
GROUP BY a.faq_id, b.faq_id, sa.n_terms, sb.n_terms, fa.question, fb.question
HAVING COUNT(*)::numeric / (sa.n_terms + sb.n_terms - COUNT(*)) >= 0.8 AND COUNT(*) >= 3
ORDER BY jaccard DESC, shared_terms DESC
LIMIT 20;

-- name: method_leaderboard | Сравнение методов: найдено в боте, время, память, MRR на тестовых вопросах; места по качеству и по скорости [CTE, JOIN, оконные RANK]
WITH per_method AS (
    SELECT a.method_id,
           COUNT(*)                        AS answers,
           COUNT(*) FILTER (WHERE a.found) AS found,
           AVG(a.latency_ms)               AS avg_latency_ms
    FROM v_method_answers a
    GROUP BY a.method_id
),
quality AS (
    SELECT method_id, AVG(COALESCE(1.0 / first_rank, 0)) AS mrr
    FROM v_test_hits
    GROUP BY method_id
)
SELECT m.name, m.preprocessing,
       p.answers,
       ROUND(100.0 * p.found / NULLIF(p.answers, 0))   AS found_pct,
       ROUND(q.mrr, 3)                                 AS test_mrr,
       ROUND(p.avg_latency_ms::numeric, 2)             AS avg_latency_ms,
       ROUND(m.memory_mb::numeric, 2)                  AS memory_mb,
       RANK() OVER (ORDER BY q.mrr DESC NULLS LAST)    AS quality_rank,
       RANK() OVER (ORDER BY p.avg_latency_ms)         AS speed_rank
FROM methods m
LEFT JOIN per_method p ON p.method_id = m.method_id
LEFT JOIN quality q    ON q.method_id = m.method_id
ORDER BY quality_rank, speed_rank;

-- name: method_agreement | Попарное согласие методов: как часто два метода дают один и тот же ответ [self-JOIN, CTE, GROUP BY]
WITH answers AS (
    SELECT request_id, method, best_faq_id
    FROM v_method_answers
    WHERE found
)
SELECT a.method AS method_a, b.method AS method_b,
       COUNT(*)                                                         AS both_found,
       ROUND(100.0 * AVG((a.best_faq_id = b.best_faq_id)::int))         AS same_answer_pct
FROM answers a
JOIN answers b ON b.request_id = a.request_id AND b.method > a.method
GROUP BY a.method, b.method
ORDER BY same_answer_pct DESC;

-- name: unique_wins | Тестовые вопросы, на которые правильно (первым) ответил только один метод [CTE, GROUP BY, HAVING, STRING_AGG]
WITH winners AS (
    SELECT test_set, query_id, query_text, query_type, method
    FROM v_test_hits
    WHERE first_rank = 1
)
SELECT test_set, query_text, query_type, MIN(method) AS only_method
FROM winners
GROUP BY test_set, query_id, query_text, query_type
HAVING COUNT(*) = 1
ORDER BY test_set, query_text;

-- name: missed_by_tfidf | Тестовые вопросы, где embeddings ответил верно, а TF-IDF — нет [подзапросы EXISTS / NOT EXISTS, JOIN]
SELECT q.test_set, q.text AS query_text, q.query_type, f.question AS expected_question
FROM test_queries q
JOIN faq f ON f.faq_id = q.true_faq_id
WHERE EXISTS (SELECT 1 FROM v_test_hits h JOIN methods m ON m.method_id = h.method_id
              WHERE h.query_id = q.query_id AND m.name = 'embeddings' AND h.first_rank = 1)
  AND NOT EXISTS (SELECT 1 FROM v_test_hits h JOIN methods m ON m.method_id = h.method_id
                  WHERE h.query_id = q.query_id AND m.name = 'tfidf' AND m.preprocessing = 'stem'
                    AND h.first_rank = 1)
ORDER BY q.test_set, q.text;

-- name: quality_by_type | Качество методов по типам формулировок (сленг, синоним, опечатка…): P@1, MRR, уверенные ошибки [представление, GROUP BY, оконные RANK]
SELECT query_type, method,
       COUNT(*)                                                                  AS queries,
       ROUND(AVG((first_rank = 1)::int), 2)                                      AS p_at_1,
       ROUND(AVG(COALESCE(1.0 / first_rank, 0)), 3)                              AS mrr,
       ROUND(AVG(confident_wrong::int), 2)                                       AS confident_wrong,
       RANK() OVER (PARTITION BY query_type ORDER BY AVG(COALESCE(1.0 / first_rank, 0)) DESC) AS place
FROM v_test_hits
WHERE query_type IS NOT NULL
GROUP BY query_type, method
ORDER BY query_type, place;

-- name: magnet_answers | «Магниты»: ответы FAQ, которые методы чаще всего выдают первыми на тестовых вопросах, хотя они неверные [JOIN, GROUP BY, HAVING, STRING_AGG]
SELECT f.faq_id, f.question,
       COUNT(*)                                             AS wrong_top1,
       COUNT(DISTINCT h.query_id)                           AS test_queries,
       STRING_AGG(DISTINCT h.query_text, ' | ')             AS lured_queries
FROM v_test_hits h
JOIN faq f ON f.faq_id = h.top_faq_id
WHERE h.first_rank IS DISTINCT FROM 1
GROUP BY f.faq_id, f.question
HAVING COUNT(*) >= 3
ORDER BY wrong_top1 DESC;

-- name: daily_activity | Активность по дням: число вопросов, накопительный итог и изменение к предыдущему дню [CTE, оконные SUM OVER, LAG]
WITH daily AS (
    SELECT date_trunc('day', asked_at)::date AS day, COUNT(*) AS questions
    FROM requests
    GROUP BY 1
)
SELECT day, questions,
       SUM(questions) OVER (ORDER BY day)          AS cumulative,
       questions - LAG(questions) OVER (ORDER BY day) AS change_vs_prev_day
FROM daily
ORDER BY day;

-- name: test_errors | Анализ ошибок на тестовых вопросах: сколько методов ответили неверно, и что они выдали [JOIN, GROUP BY, HAVING, STRING_AGG]
SELECT h.test_set, h.query_text AS test_query, h.query_type,
       MIN(ft.question)                                                          AS expected_question,
       COUNT(*) FILTER (WHERE h.first_rank IS DISTINCT FROM 1)                   AS wrong_methods,
       COUNT(*)                                                                  AS methods,
       STRING_AGG(DISTINCT fp.question, ' | ') FILTER (WHERE h.first_rank IS DISTINCT FROM 1) AS wrong_answers
FROM v_test_hits h
JOIN test_queries q ON q.query_id = h.query_id
JOIN faq ft ON ft.faq_id = q.true_faq_id
JOIN faq fp ON fp.faq_id = h.top_faq_id
GROUP BY h.test_set, h.query_id, h.query_text, h.query_type
HAVING COUNT(*) FILTER (WHERE h.first_rank IS DISTINCT FROM 1) >= 1
ORDER BY wrong_methods DESC, h.test_set, h.query_text;

-- name: unanswered_gaps | Вопросы без ответа: сколько раз задавали и ближайший вопрос FAQ [представление, JOIN, GROUP BY, оконные DENSE_RANK]
SELECT DENSE_RANK() OVER (ORDER BY COUNT(*) DESC) AS priority,
       lower(u.query_text)                        AS question,
       COUNT(*)                                   AS times,
       (ARRAY_AGG(f.question ORDER BY u.best_score DESC NULLS LAST))[1] AS closest_faq,
       ROUND(MAX(u.best_score)::numeric, 2)       AS best_score
FROM v_unanswered u
LEFT JOIN faq f ON f.faq_id = u.best_faq_id
GROUP BY lower(u.query_text)
ORDER BY priority, question;
