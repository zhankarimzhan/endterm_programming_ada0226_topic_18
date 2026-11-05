"""Статистика бота: SQL-запросы к нормализованной схеме (requests, method_runs, candidates, resolutions, runs)
и представлениям v_method_answers / v_unanswered / v_test_hits (sql/init/03_views.sql).
Используется командой /stats, дашбордами и API."""
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from db import run_query

# Общие показатели по вопросам пользователей
TOTALS_SQL = """
    WITH per_request AS (
        SELECT r.request_id, COALESCE(BOOL_OR(a.found), false) AS answered
        FROM requests r LEFT JOIN v_method_answers a ON a.request_id = r.request_id
        GROUP BY r.request_id
    )
    SELECT COUNT(*)                             AS questions,
           COUNT(*) FILTER (WHERE answered)     AS answered,
           COUNT(*) FILTER (WHERE NOT answered) AS not_found
    FROM per_request
"""

# По методам: доля найденных, среднее сходство, время поиска, ресурсы и качество на тестовых вопросах
# (MRR последнего прогона на каждом наборе); место — по MRR на базовом наборе
BY_METHOD_SQL = """
    WITH per_method AS (
        SELECT method_id,
               COUNT(*)                        AS questions,
               COUNT(*) FILTER (WHERE found)   AS answered,
               AVG(score) FILTER (WHERE found) AS avg_score,
               AVG(latency_ms)                 AS avg_latency_ms
        FROM v_method_answers
        GROUP BY method_id
    ),
    last_runs AS (
        SELECT DISTINCT ON (method_id, test_set) method_id, test_set, mrr
        FROM runs
        ORDER BY method_id, test_set, created_at DESC
    )
    SELECT m.name, p.questions, p.answered,
           ROUND(100.0 * p.answered / NULLIF(p.questions, 0))  AS found_pct,
           ROUND(p.avg_score::numeric, 2)                      AS avg_score,
           ROUND(p.avg_latency_ms::numeric, 1)                 AS avg_latency_ms,
           ROUND(m.memory_mb::numeric, 2)                      AS memory_mb,
           ROUND(m.fit_seconds::numeric, 2)                    AS fit_seconds,
           ROUND(b.mrr, 3)                                     AS mrr_base,
           ROUND(pp.mrr, 3)                                    AS mrr_paraphrases,
           RANK() OVER (ORDER BY b.mrr DESC NULLS LAST)        AS rank
    FROM per_method p
    JOIN methods m ON m.method_id = p.method_id
    LEFT JOIN last_runs b  ON b.method_id = m.method_id AND b.test_set = 'base'
    LEFT JOIN last_runs pp ON pp.method_id = m.method_id AND pp.test_set = 'paraphrases'
    ORDER BY rank, p.questions DESC
"""

# Ответ каждого метода на каждый запрос (вкладка «Запросы»)
CHAT_LOG_SQL = """
    SELECT a.request_id, a.asked_at, a.query_text AS user_query, a.mode, a.method,
           f.question AS matched_question, f.answer AS matched_answer,
           ROUND(a.score::numeric, 3)      AS score,
           ROUND(a.latency_ms::numeric, 1) AS latency_ms,
           a.found
    FROM v_method_answers a
    LEFT JOIN faq f ON f.faq_id = a.best_faq_id
    ORDER BY a.asked_at DESC, a.method
"""

# Режим сравнения: ответы всех методов на запрос (вкладка «Совпадения»)
COMPARISON_SQL = """
    SELECT a.request_id, a.asked_at, a.query_text AS user_query, a.method,
           CASE WHEN a.found THEN f.question END AS matched_question,
           ROUND(a.score::numeric, 3)      AS score,
           ROUND(a.latency_ms::numeric, 1) AS latency_ms
    FROM v_method_answers a
    LEFT JOIN faq f ON f.faq_id = a.best_faq_id
    WHERE a.mode = 'compare'
    ORDER BY a.asked_at DESC, a.method
"""

# Вопросов по дням и режимам
DAILY_SQL = """
    SELECT date_trunc('day', asked_at)::date AS day, mode, COUNT(*) AS questions
    FROM requests
    GROUP BY 1, 2
    ORDER BY 1
"""

# Какие ответы FAQ методы выдают чаще всего
TOP_MATCHED_SQL = """
    SELECT f.faq_id, f.question, COUNT(*) AS times,
           COUNT(DISTINCT a.request_id)    AS requests,
           ROUND(AVG(a.score)::numeric, 2) AS avg_score
    FROM v_method_answers a
    JOIN faq f ON f.faq_id = a.best_faq_id
    WHERE a.found
    GROUP BY f.faq_id, f.question
    ORDER BY times DESC
    LIMIT :limit
"""

# Предложения для пополнения FAQ: вопросы без ответа, сгруппированные по тексту
SUGGESTIONS_SQL = """
    SELECT lower(u.query_text)                                               AS question,
           COUNT(*)                                                          AS times,
           (ARRAY_AGG(f.question ORDER BY u.best_score DESC NULLS LAST))[1]  AS best_candidate,
           ROUND(MAX(u.best_score)::numeric, 2)                              AS best_score,
           MAX(u.asked_at)                                                   AS last_asked,
           ARRAY_AGG(u.request_id::text)                                     AS ids
    FROM v_unanswered u
    LEFT JOIN faq f ON f.faq_id = u.best_faq_id
    GROUP BY lower(u.query_text)
    ORDER BY times DESC, last_asked DESC
"""

# Оценка на тестовых вопросах: последний прогон каждого метода на каждом наборе
# (вариант предобработки — отдельный метод); место — внутри набора
EVALUATION_SQL = """
    SELECT r.test_set, m.title AS method, m.preprocessing,
           ROUND(r.p_at_1, 3) AS p_at_1, ROUND(r.p_at_3, 3) AS p_at_3, ROUND(r.mrr, 3) AS mrr,
           ROUND(r.time_ms, 2) AS time_ms, ROUND(r.memory_mb, 2) AS memory_mb,
           (SELECT COUNT(DISTINCT query_id) FROM predictions p WHERE p.run_id = r.run_id) AS test_queries,
           RANK() OVER (PARTITION BY r.test_set ORDER BY r.mrr DESC) AS place,
           r.created_at
    FROM (SELECT DISTINCT ON (method_id, test_set) * FROM runs ORDER BY method_id, test_set, created_at DESC) r
    JOIN methods m ON m.method_id = r.method_id
    ORDER BY r.test_set, place, r.time_ms
"""

# Разбивка оценки по типу формулировки или теме (набор paraphrases):
# доля верных первым и в топ-3, MRR и доля уверенных ошибок (неверный ответ выше порога метода)
BREAKDOWN_SQL = """
    SELECT {column} AS bucket, method, preprocessing,
           COUNT(*)                                                       AS queries,
           ROUND(AVG(COALESCE(first_rank = 1, false)::int), 3)                           AS p_at_1,
           ROUND(AVG((first_rank IS NOT NULL)::int), 3)                   AS p_at_3,
           ROUND(AVG(COALESCE(1.0 / first_rank, 0)), 3)                   AS mrr,
           ROUND(AVG(confident_wrong::int), 3)                            AS confident_wrong
    FROM v_test_hits
    WHERE test_set = :test_set AND {column} IS NOT NULL
    GROUP BY {column}, method, preprocessing
    ORDER BY {column}, mrr DESC
"""
BREAKDOWNS = {"type": "query_type", "topic": "topic"}

RESOLVE_SQL = """
    INSERT INTO resolutions (request_id)
    SELECT unnest(CAST(:ids AS uuid[]))
    ON CONFLICT (request_id) DO NOTHING
"""


def get_totals(engine: Engine) -> dict:
    return run_query(TOTALS_SQL, engine).iloc[0].to_dict()


def get_method_stats(engine: Engine) -> pd.DataFrame:
    return run_query(BY_METHOD_SQL, engine)


def get_chat_log(engine: Engine) -> pd.DataFrame:
    return run_query(CHAT_LOG_SQL, engine)


def get_comparison(engine: Engine) -> pd.DataFrame:
    return run_query(COMPARISON_SQL, engine)


def get_daily(engine: Engine) -> pd.DataFrame:
    return run_query(DAILY_SQL, engine)


def get_top_matched(engine: Engine, limit: int = 10) -> pd.DataFrame:
    return run_query(TOP_MATCHED_SQL, engine, {"limit": limit})


def get_suggestions(engine: Engine) -> pd.DataFrame:
    return run_query(SUGGESTIONS_SQL, engine)


def get_evaluation(engine: Engine) -> pd.DataFrame:
    return run_query(EVALUATION_SQL, engine)


def get_evaluation_breakdown(engine: Engine, by: str = "type", test_set: str = "paraphrases") -> pd.DataFrame:
    """Метрики по типам формулировок (by='type') или темам (by='topic')."""
    return run_query(BREAKDOWN_SQL.format(column=BREAKDOWNS[by]), engine, {"test_set": test_set})


def get_top_unanswered(engine: Engine, limit: int = 5) -> pd.DataFrame:
    return get_suggestions(engine).head(limit)


def mark_resolved(engine: Engine, ids: list[str]) -> None:
    """Отмечает вопросы как обработанные (ответ добавлен в FAQ)."""
    with engine.begin() as conn:
        conn.execute(text(RESOLVE_SQL), {"ids": [str(i) for i in ids]})


def format_stats(engine: Engine) -> str:
    """Текстовый отчёт для команды /stats."""
    t = get_totals(engine)
    lines = ["📊 Статистика бота"]
    if t["questions"]:
        lines.append(f"Вопросов: {t['questions']} (ответ найден: {t['answered']}, не найден: {t['not_found']})")
        lines += ["", "По методам (место — по MRR на тестовых вопросах):"]
        for r in get_method_stats(engine).itertuples():
            avg = f"{r.avg_score:.2f}" if pd.notna(r.avg_score) else "—"
            lat = f"{r.avg_latency_ms:.1f} мс" if pd.notna(r.avg_latency_ms) else "—"
            mem = f"{r.memory_mb:.1f} МБ" if pd.notna(r.memory_mb) else "—"
            lines.append(f"{r.rank}. {r.name}: ответов {r.questions}, найдено {int(r.found_pct)}%, "
                         f"ср. сходство {avg}, поиск {lat}, память {mem}")
    else:
        lines.append("Пока нет ни одного вопроса.")
    ev = get_evaluation(engine)
    for test_set, title in (("base", "базовые перефразы"), ("paraphrases", "разные формулировки")):
        part = ev[ev["test_set"] == test_set]
        if part.empty:
            continue
        lines += ["", f"Тестовые вопросы — {title} ({int(part['test_queries'].max())} шт., место — по MRR):"]
        lines += [f"{r.place}. {r.method}: P@1 {r.p_at_1:.2f}, P@3 {r.p_at_3:.2f}, MRR {r.mrr:.2f}, {r.time_ms:.1f} мс"
                  for r in part.itertuples()]
    top = get_top_unanswered(engine)
    if not top.empty:
        lines += ["", "Частые вопросы без ответа:"]
        lines += [f"• {r.question} ({r.times}×)" for r in top.itertuples()]
    return "\n".join(lines)


if __name__ == "__main__":
    from db import get_engine
    print(format_stats(get_engine()))
