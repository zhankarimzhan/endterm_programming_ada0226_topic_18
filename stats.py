"""Статистика бота: SQL-запросы к нормализованной схеме (requests, method_runs, candidates, feedback, resolutions)
и представлениям v_method_answers / v_unanswered (sql/init/03_views.sql). Используется командой /stats и дашбордом."""
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from database import run_query

# Общие показатели: вопросы считаются по requests, оценки — по ответам методов
TOTALS_SQL = """
    WITH per_request AS (
        SELECT r.request_id, COALESCE(BOOL_OR(a.found), false) AS answered
        FROM requests r LEFT JOIN v_method_answers a ON a.request_id = r.request_id
        GROUP BY r.request_id
    )
    SELECT COUNT(*)                             AS questions,
           COUNT(*) FILTER (WHERE answered)     AS answered,
           COUNT(*) FILTER (WHERE NOT answered) AS not_found,
           (SELECT COUNT(*) FROM v_method_answers WHERE helpful)         AS likes,
           (SELECT COUNT(*) FROM v_method_answers WHERE helpful = false) AS dislikes
    FROM per_request
"""

# По методам: доля найденных, среднее сходство, отзывы, доля довольных, время поиска, ресурсы; место по доле 👍
BY_METHOD_SQL = """
    WITH per_method AS (
        SELECT method_id,
               COUNT(*)                                 AS questions,
               COUNT(*) FILTER (WHERE found)            AS answered,
               AVG(score) FILTER (WHERE found)          AS avg_score,
               COUNT(*) FILTER (WHERE helpful)          AS likes,
               COUNT(*) FILTER (WHERE helpful = false)  AS dislikes,
               AVG(latency_ms)                          AS avg_latency_ms
        FROM v_method_answers
        GROUP BY method_id
    )
    SELECT m.name, p.questions, p.answered,
           ROUND(100.0 * p.answered / NULLIF(p.questions, 0))        AS found_pct,
           ROUND(p.avg_score::numeric, 2)                            AS avg_score,
           p.likes, p.dislikes,
           ROUND(100.0 * p.likes / NULLIF(p.likes + p.dislikes, 0))  AS satisfaction_pct,
           ROUND(p.avg_latency_ms::numeric, 1)                       AS avg_latency_ms,
           ROUND(m.memory_mb::numeric, 2)                            AS memory_mb,
           ROUND(m.fit_seconds::numeric, 2)                          AS fit_seconds,
           RANK() OVER (ORDER BY 1.0 * p.likes / NULLIF(p.likes + p.dislikes, 0) DESC NULLS LAST) AS rank
    FROM per_method p
    JOIN methods m ON m.method_id = p.method_id
    ORDER BY rank, p.questions DESC
"""

# Ответ каждого метода на каждый запрос (вкладка «Запросы»)
CHAT_LOG_SQL = """
    SELECT a.request_id, a.asked_at, a.query_text AS user_query, a.mode, a.method,
           f.question AS matched_question, f.answer AS matched_answer,
           ROUND(a.score::numeric, 3)      AS score,
           ROUND(a.latency_ms::numeric, 1) AS latency_ms,
           a.found,
           CASE WHEN a.helpful THEN '👍' WHEN a.helpful = false THEN '👎' ELSE '' END AS feedback
    FROM v_method_answers a
    LEFT JOIN faq f ON f.faq_id = a.best_faq_id
    ORDER BY a.asked_at DESC, a.method
"""

# Режим сравнения: ответы всех методов на запрос (вкладка «Совпадения»)
COMPARISON_SQL = """
    SELECT a.request_id, a.asked_at, a.query_text AS user_query, a.method,
           CASE WHEN a.found THEN f.question END AS matched_question,
           ROUND(a.score::numeric, 3)      AS score,
           ROUND(a.latency_ms::numeric, 1) AS latency_ms,
           CASE WHEN a.helpful THEN '👍' WHEN a.helpful = false THEN '👎' ELSE '' END AS feedback
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

# Какие ответы FAQ методы выдают чаще всего и как их оценивают
TOP_MATCHED_SQL = """
    SELECT f.faq_id, f.question, COUNT(*) AS times,
           ROUND(AVG(a.score)::numeric, 2)            AS avg_score,
           COUNT(*) FILTER (WHERE a.helpful)          AS likes,
           COUNT(*) FILTER (WHERE a.helpful = false)  AS dislikes
    FROM v_method_answers a
    JOIN faq f ON f.faq_id = a.best_faq_id
    WHERE a.found
    GROUP BY f.faq_id, f.question
    ORDER BY times DESC
    LIMIT :limit
"""

# Предложения для пополнения FAQ: вопросы без подходящего ответа, сгруппированные по тексту
SUGGESTIONS_SQL = """
    SELECT lower(u.query_text)                                               AS question,
           COUNT(*)                                                          AS times,
           STRING_AGG(DISTINCT u.reason, ', ')                               AS reasons,
           (ARRAY_AGG(f.question ORDER BY u.best_score DESC NULLS LAST))[1]  AS best_candidate,
           ROUND(MAX(u.best_score)::numeric, 2)                              AS best_score,
           MAX(u.asked_at)                                                   AS last_asked,
           ARRAY_AGG(u.request_id::text)                                     AS ids
    FROM v_unanswered u
    LEFT JOIN faq f ON f.faq_id = u.best_faq_id
    GROUP BY lower(u.query_text)
    ORDER BY times DESC, last_asked DESC
"""

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


def get_top_unanswered(engine: Engine, limit: int = 5) -> pd.DataFrame:
    return get_suggestions(engine).head(limit)


def mark_resolved(engine: Engine, ids: list[str]) -> None:
    """Отмечает вопросы как обработанные (ответ добавлен в FAQ)."""
    with engine.begin() as conn:
        conn.execute(text(RESOLVE_SQL), {"ids": [str(i) for i in ids]})


def format_stats(engine: Engine) -> str:
    """Текстовый отчёт для команды /stats."""
    t = get_totals(engine)
    if not t["questions"]:
        return "Пока нет ни одного вопроса."
    rated = t["likes"] + t["dislikes"]
    lines = ["📊 Статистика бота",
             f"Вопросов: {t['questions']} (ответ найден: {t['answered']}, не найден: {t['not_found']})",
             f"Оценки ответов методов: 👍 {t['likes']}  👎 {t['dislikes']}"
             + (f"  — довольны {round(100 * t['likes'] / rated)}%" if rated else ""),
             "", "По методам (место — по доле 👍):"]
    for r in get_method_stats(engine).itertuples():
        sat = f"{int(r.satisfaction_pct)}%" if pd.notna(r.satisfaction_pct) else "—"
        avg = f"{r.avg_score:.2f}" if pd.notna(r.avg_score) else "—"
        lat = f"{r.avg_latency_ms:.1f} мс" if pd.notna(r.avg_latency_ms) else "—"
        mem = f"{r.memory_mb:.1f} МБ" if pd.notna(r.memory_mb) else "—"
        lines.append(f"{r.rank}. {r.name}: ответов {r.questions}, найдено {int(r.found_pct)}%, ср. сходство {avg}, "
                     f"👍 {r.likes} 👎 {r.dislikes}, довольны {sat}, поиск {lat}, память {mem}")
    top = get_top_unanswered(engine)
    if not top.empty:
        lines += ["", "Частые вопросы без ответа:"]
        lines += [f"• {r.question} ({r.times}×, {r.reasons})" for r in top.itertuples()]
    return "\n".join(lines)


if __name__ == "__main__":
    from database import get_engine
    print(format_stats(get_engine()))
