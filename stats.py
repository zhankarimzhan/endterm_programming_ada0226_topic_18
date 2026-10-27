"""Статистика работы бота по истории вопросов и отзывам (SQL-запросы к chat_log и unanswered_questions)."""
import pandas as pd
from sqlalchemy.engine import Engine

from database import run_query

# Общие показатели за всё время
TOTALS_SQL = """
    SELECT COUNT(*)                                   AS questions,
           COUNT(*) FILTER (WHERE faq_id IS NOT NULL) AS answered,
           COUNT(*) FILTER (WHERE faq_id IS NULL)     AS not_found,
           COUNT(*) FILTER (WHERE helpful)            AS likes,
           COUNT(*) FILTER (WHERE helpful = false)    AS dislikes
    FROM chat_log
"""

# По методам: доля найденных ответов, средняя оценка, отзывы и доля довольных среди оценённых ответов
BY_METHOD_SQL = """
    WITH per_method AS (
        SELECT m.name,
               COUNT(*)                                   AS questions,
               COUNT(*) FILTER (WHERE c.faq_id IS NOT NULL) AS answered,
               AVG(c.score) FILTER (WHERE c.faq_id IS NOT NULL) AS avg_score,
               COUNT(*) FILTER (WHERE c.helpful)          AS likes,
               COUNT(*) FILTER (WHERE c.helpful = false)  AS dislikes
        FROM chat_log c
        JOIN methods m ON m.method_id = c.method_id
        GROUP BY m.name
    )
    SELECT name, questions, answered,
           ROUND(100.0 * answered / NULLIF(questions, 0)) AS found_pct,
           ROUND(avg_score::numeric, 2)                  AS avg_score,
           likes, dislikes,
           ROUND(100.0 * likes / NULLIF(likes + dislikes, 0)) AS satisfaction_pct,
           RANK() OVER (ORDER BY 100.0 * likes / NULLIF(likes + dislikes, 0) DESC NULLS LAST) AS rank
    FROM per_method
    ORDER BY rank, questions DESC
"""

# Частые вопросы без подходящего ответа, ещё не добавленные в FAQ
TOP_UNANSWERED_SQL = """
    SELECT lower(user_query) AS question,
           COUNT(*)          AS times,
           STRING_AGG(DISTINCT reason, ', ') AS reasons
    FROM unanswered_questions
    WHERE NOT resolved
    GROUP BY lower(user_query)
    ORDER BY times DESC, MAX(created_at) DESC
    LIMIT :limit
"""


# Все вопросы с найденным ответом, методом и отзывом (для таблицы запросов в дашборде)
CHAT_LOG_SQL = """
    SELECT c.log_id, c.asked_at, c.user_query, m.name AS method,
           f.question AS matched_question, f.answer AS matched_answer,
           ROUND(c.score::numeric, 3) AS score,
           (c.faq_id IS NOT NULL) AS found,
           CASE WHEN c.helpful THEN '👍' WHEN c.helpful = false THEN '👎' ELSE '' END AS feedback
    FROM chat_log c
    LEFT JOIN methods m ON m.method_id = c.method_id
    LEFT JOIN faq f     ON f.faq_id = c.faq_id
    ORDER BY c.asked_at DESC
"""

# Вопросов по дням и методам
DAILY_SQL = """
    SELECT date_trunc('day', c.asked_at)::date AS day, m.name AS method, COUNT(*) AS questions
    FROM chat_log c JOIN methods m ON m.method_id = c.method_id
    GROUP BY 1, 2 ORDER BY 1
"""

# Какие вопросы FAQ бот выдаёт чаще всего и как их оценивают
TOP_MATCHED_SQL = """
    SELECT f.faq_id, f.question, COUNT(*) AS times,
           ROUND(AVG(c.score)::numeric, 2) AS avg_score,
           COUNT(*) FILTER (WHERE c.helpful)         AS likes,
           COUNT(*) FILTER (WHERE c.helpful = false) AS dislikes
    FROM chat_log c JOIN faq f ON f.faq_id = c.faq_id
    GROUP BY f.faq_id, f.question
    ORDER BY times DESC
    LIMIT :limit
"""

# Предложения для пополнения FAQ: вопросы без подходящего ответа, сгруппированные по тексту
SUGGESTIONS_SQL = """
    WITH grouped AS (
        SELECT lower(u.user_query) AS question,
               COUNT(*) AS times,
               STRING_AGG(DISTINCT u.reason, ', ') AS reasons,
               STRING_AGG(DISTINCT m.name, ', ')   AS methods,
               MAX(u.created_at) AS last_asked,
               ARRAY_AGG(u.id) AS ids
        FROM unanswered_questions u LEFT JOIN methods m ON m.method_id = u.method_id
        WHERE NOT u.resolved
        GROUP BY lower(u.user_query)
    ),
    best AS (   -- лучший кандидат, который бот нашёл для этого вопроса
        SELECT DISTINCT ON (lower(u.user_query)) lower(u.user_query) AS question,
               f.question AS best_candidate, ROUND(u.best_score::numeric, 2) AS best_score
        FROM unanswered_questions u LEFT JOIN faq f ON f.faq_id = u.best_faq_id
        WHERE NOT u.resolved
        ORDER BY lower(u.user_query), u.best_score DESC NULLS LAST
    )
    SELECT g.question, g.times, g.reasons, g.methods, b.best_candidate, b.best_score, g.last_asked, g.ids
    FROM grouped g JOIN best b USING (question)
    ORDER BY g.times DESC, g.last_asked DESC
"""

RESOLVE_SQL = "UPDATE unanswered_questions SET resolved = true WHERE id = ANY(:ids)"


def get_chat_log(engine: Engine) -> pd.DataFrame:
    return run_query(CHAT_LOG_SQL, engine)


def get_daily(engine: Engine) -> pd.DataFrame:
    return run_query(DAILY_SQL, engine)


def get_top_matched(engine: Engine, limit: int = 10) -> pd.DataFrame:
    return run_query(TOP_MATCHED_SQL, engine, {"limit": limit})


def get_suggestions(engine: Engine) -> pd.DataFrame:
    return run_query(SUGGESTIONS_SQL, engine)


def mark_resolved(engine: Engine, ids: list[int]) -> None:
    """Отмечает вопросы как обработанные (ответ добавлен в FAQ)."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(RESOLVE_SQL), {"ids": [int(i) for i in ids]})


def get_totals(engine: Engine) -> dict:
    return run_query(TOTALS_SQL, engine).iloc[0].to_dict()


def get_method_stats(engine: Engine) -> pd.DataFrame:
    return run_query(BY_METHOD_SQL, engine)


def get_top_unanswered(engine: Engine, limit: int = 5) -> pd.DataFrame:
    return run_query(TOP_UNANSWERED_SQL, engine, {"limit": limit})


def format_stats(engine: Engine) -> str:
    """Текстовый отчёт для команды /stats."""
    t = get_totals(engine)
    if not t["questions"]:
        return "Пока нет ни одного вопроса."
    rated = t["likes"] + t["dislikes"]
    lines = ["📊 Статистика бота",
             f"Вопросов: {t['questions']} (ответ найден: {t['answered']}, не найден: {t['not_found']})",
             f"Отзывы: 👍 {t['likes']}  👎 {t['dislikes']}"
             + (f"  — довольны {round(100 * t['likes'] / rated)}%" if rated else ""),
             "", "По методам:"]
    for r in get_method_stats(engine).itertuples():
        sat = f"{int(r.satisfaction_pct)}%" if pd.notna(r.satisfaction_pct) else "—"
        avg = f"{r.avg_score:.2f}" if pd.notna(r.avg_score) else "—"
        lines.append(f"• {r.name}: вопросов {r.questions}, найдено {int(r.found_pct)}%, ср. сходство {avg}, "
                     f"👍 {r.likes} 👎 {r.dislikes}, довольны {sat}")
    top = get_top_unanswered(engine)
    if not top.empty:
        lines += ["", "Частые вопросы без ответа:"]
        lines += [f"• {r.question} ({r.times}×, {r.reasons})" for r in top.itertuples()]
    return "\n".join(lines)


if __name__ == "__main__":
    from database import get_engine
    print(format_stats(get_engine()))
