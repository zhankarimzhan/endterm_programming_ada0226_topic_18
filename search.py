"""Подготовка методов поиска по FAQ из базы и запись истории вопросов."""
import logging
import time

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from methods import METHOD_CLASSES, SimilarityMethod

REGISTER_SQL = text("""
    INSERT INTO methods (name, preprocessing) VALUES (:name, :prep)
    ON CONFLICT (name, preprocessing) DO NOTHING
""")

LOG_SQL = text("""
    INSERT INTO chat_log (user_query, method_id, faq_id, score)
    SELECT :q, method_id, :faq_id, :score FROM methods WHERE name = :name AND preprocessing = :prep
    RETURNING log_id
""")

FEEDBACK_SQL = text("UPDATE chat_log SET helpful = :helpful WHERE log_id = :log_id")

# Данные берутся из chat_log; лучший кандидат можно передать явно (когда ответ не выдан, в chat_log faq_id пустой)
UNANSWERED_SQL = text("""
    INSERT INTO unanswered_questions (log_id, user_query, method_id, best_faq_id, best_score, reason)
    SELECT log_id, user_query, method_id, COALESCE(:best_faq_id, faq_id), score, :reason
    FROM chat_log WHERE log_id = :log_id
    ON CONFLICT (log_id) DO NOTHING
""")


def load_faq(engine: Engine) -> pd.DataFrame:
    """Вопросы и ответы из таблицы faq."""
    return pd.read_sql("SELECT faq_id, question, answer FROM faq ORDER BY faq_id", engine)


def register_methods(engine: Engine, methods: dict[str, SimilarityMethod]) -> None:
    """Добавляет методы в таблицу methods (если их там ещё нет)."""
    with engine.begin() as conn:
        for m in methods.values():
            conn.execute(REGISTER_SQL, {"name": m.name, "prep": m.preprocessing})


def build_methods(engine: Engine, names: list[str] | None = None) -> dict[str, SimilarityMethod]:
    """Создаёт и обучает методы. Метод, который не удалось подготовить (например, нет сети для модели), пропускается."""
    faq = load_faq(engine)
    methods = {}
    for name in names or METHOD_CLASSES:
        start = time.perf_counter()
        try:
            methods[name] = METHOD_CLASSES[name](engine=engine).fit(faq)
        except Exception:
            logging.exception("Метод %s не удалось подготовить, он будет недоступен", name)
            continue
        logging.info("Метод %s готов за %.1f с", name, time.perf_counter() - start)
    register_methods(engine, methods)
    return methods


def log_question(engine: Engine, query: str, method: SimilarityMethod, faq_id: int | None, score: float | None) -> int | None:
    """Сохраняет вопрос, метод и найденный ответ в chat_log (без данных о пользователе); возвращает log_id."""
    with engine.begin() as conn:
        return conn.execute(LOG_SQL, {"q": query, "faq_id": faq_id, "score": score,
                                      "name": method.name, "prep": method.preprocessing}).scalar()


def save_feedback(engine: Engine, log_id: int, helpful: bool) -> None:
    """Отзыв пользователя на ответ: 👍 (True) или 👎 (False)."""
    with engine.begin() as conn:
        conn.execute(FEEDBACK_SQL, {"log_id": log_id, "helpful": helpful})


def save_unanswered(engine: Engine, log_id: int, reason: str, best_faq_id: int | None = None) -> None:
    """Сохраняет вопрос без подходящего ответа: reason = 'not_found' (ничего не найдено) или 'bad_answer' (👎)."""
    with engine.begin() as conn:
        conn.execute(UNANSWERED_SQL, {"log_id": log_id, "reason": reason, "best_faq_id": best_faq_id})


if __name__ == "__main__":
    from database import get_engine
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    all_methods = build_methods(get_engine())
    for q in ["как поступить в аиту", "сколько стоит обучение", "есть ли общага"]:
        print(f"\n{q!r}")
        for m in all_methods.values():
            best = m.search(q, k=1)[0]
            mark = "" if best["score"] >= m.min_score else "  (ниже порога)"
            print(f"  {m.title:<22} [{best['score']:.2f}] {best['question'][:70]}{mark}")
