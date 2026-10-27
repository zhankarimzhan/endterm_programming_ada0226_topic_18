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

-- name: method_leaderboard | Сравнение методов: найдено, доля 👍, время поиска, память; места по качеству и по скорости [CTE, JOIN, оконные RANK]
WITH per_method AS (
    SELECT a.method_id,
           COUNT(*)                                AS answers,
           COUNT(*) FILTER (WHERE a.found)         AS found,
           COUNT(*) FILTER (WHERE a.helpful)       AS likes,
           COUNT(*) FILTER (WHERE a.helpful = false) AS dislikes,
           AVG(a.latency_ms)                       AS avg_latency_ms
    FROM v_method_answers a
    GROUP BY a.method_id
)
SELECT m.name,
       p.answers,
       ROUND(100.0 * p.found / NULLIF(p.answers, 0))             AS found_pct,
       ROUND(100.0 * p.likes / NULLIF(p.likes + p.dislikes, 0))  AS satisfaction_pct,
       ROUND(p.avg_latency_ms::numeric, 2)                       AS avg_latency_ms,
       ROUND(m.memory_mb::numeric, 2)                            AS memory_mb,
       RANK() OVER (ORDER BY 1.0 * p.likes / NULLIF(p.likes + p.dislikes, 0) DESC NULLS LAST) AS quality_rank,
       RANK() OVER (ORDER BY p.avg_latency_ms)                   AS speed_rank
FROM per_method p
JOIN methods m ON m.method_id = p.method_id
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

-- name: unique_wins | Запросы, где ответ, одобренный пользователем, нашёл только один метод [CTE, GROUP BY, HAVING, подзапрос EXISTS]
WITH approved AS (
    SELECT a.request_id, a.query_text, a.method
    FROM v_method_answers a
    WHERE a.helpful
      AND EXISTS (SELECT 1 FROM feedback f WHERE f.request_id = a.request_id AND f.helpful)
)
SELECT request_id, MIN(query_text) AS query_text, MIN(method) AS only_method
FROM approved
GROUP BY request_id
HAVING COUNT(*) = 1;

-- name: missed_by_tfidf | Вопросы, где embeddings нашёл одобренный ответ, а TF-IDF — нет [подзапросы EXISTS / NOT EXISTS, JOIN]
SELECT r.request_id, r.query_text, f.question AS approved_answer
FROM requests r
JOIN feedback fb ON fb.request_id = r.request_id AND fb.helpful
JOIN faq f       ON f.faq_id = fb.faq_id
WHERE EXISTS (SELECT 1 FROM v_method_answers a
              WHERE a.request_id = r.request_id AND a.method = 'embeddings' AND a.best_faq_id = fb.faq_id AND a.found)
  AND NOT EXISTS (SELECT 1 FROM v_method_answers a
                  WHERE a.request_id = r.request_id AND a.method = 'tfidf' AND a.best_faq_id = fb.faq_id AND a.found);

-- name: rank_of_approved | На каком месте у каждого метода стоял одобренный ответ (MRR по реальным отзывам) [JOIN, CTE, агрегаты]
WITH approved AS (
    SELECT request_id, faq_id FROM feedback WHERE helpful
),
positions AS (
    SELECT mr.method_id, ap.request_id,
           MIN(c.rank) AS approved_rank           -- NULL, если одобренного ответа нет в топ-k метода
    FROM approved ap
    JOIN method_runs mr ON mr.request_id = ap.request_id
    LEFT JOIN candidates c ON c.request_id = mr.request_id AND c.method_id = mr.method_id AND c.faq_id = ap.faq_id
    GROUP BY mr.method_id, ap.request_id
)
SELECT m.name,
       COUNT(*)                                                   AS rated_requests,
       COUNT(*) FILTER (WHERE approved_rank = 1)                  AS top1,
       COUNT(*) FILTER (WHERE approved_rank <= 3)                 AS top3,
       ROUND(AVG(COALESCE(1.0 / approved_rank, 0)), 3)            AS mrr
FROM positions p
JOIN methods m ON m.method_id = p.method_id
GROUP BY m.name
ORDER BY mrr DESC;

-- name: magnet_answers | «Магниты»: ответы FAQ, которые методы выдают часто, но пользователи отклоняют [CTE, JOIN, GROUP BY, HAVING]
WITH shown AS (
    SELECT best_faq_id AS faq_id, helpful
    FROM v_method_answers
    WHERE found
)
SELECT f.faq_id, f.question,
       COUNT(*)                                   AS times_shown,
       COUNT(*) FILTER (WHERE s.helpful = false)  AS rejected,
       COUNT(*) FILTER (WHERE s.helpful)          AS approved
FROM shown s
JOIN faq f ON f.faq_id = s.faq_id
GROUP BY f.faq_id, f.question
HAVING COUNT(*) FILTER (WHERE s.helpful = false) >= 1
ORDER BY rejected DESC, times_shown DESC;

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

-- name: unanswered_gaps | Вопросы без ответа: сколько раз задавали, причина и ближайший вопрос FAQ [представление, JOIN, GROUP BY, оконные DENSE_RANK]
SELECT DENSE_RANK() OVER (ORDER BY COUNT(*) DESC) AS priority,
       lower(u.query_text)                        AS question,
       COUNT(*)                                   AS times,
       STRING_AGG(DISTINCT u.reason, ', ')        AS reasons,
       (ARRAY_AGG(f.question ORDER BY u.best_score DESC NULLS LAST))[1] AS closest_faq
FROM v_unanswered u
LEFT JOIN faq f ON f.faq_id = u.best_faq_id
GROUP BY lower(u.query_text)
ORDER BY priority, question;
