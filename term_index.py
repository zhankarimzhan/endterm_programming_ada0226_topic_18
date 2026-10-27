"""Обратный индекс в PostgreSQL: стеммы слов вопросов FAQ (terms) и их частота в каждом вопросе (faq_terms).
По нему SQL-запросами считаются частоты слов, документная частота, TF-IDF и похожие вопросы (см. queries.sql)."""
from collections import Counter

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from preprocessing import preprocess


def build_term_rows(faq: pd.DataFrame, mode: str = "stem") -> tuple[list[str], list[tuple[int, str, int]]]:
    """Словарь стеммов и тройки (faq_id, стемм, частота в вопросе)."""
    rows = []
    for faq_id, question in zip(faq["faq_id"], faq["question"]):
        for term, tf in Counter(preprocess(question, mode)).items():
            rows.append((int(faq_id), term, tf))
    return sorted({term for _, term, _ in rows}), rows


def load_term_index(engine: Engine, faq: pd.DataFrame) -> None:
    """Перестраивает terms и faq_terms по текущему FAQ."""
    vocabulary, rows = build_term_rows(faq)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE faq_terms, terms RESTART IDENTITY"))
        conn.execute(text("INSERT INTO terms (term) VALUES (:term)"), [{"term": t} for t in vocabulary])
        term_id = dict(conn.execute(text("SELECT term, term_id FROM terms")).all())
        conn.execute(text("INSERT INTO faq_terms (faq_id, term_id, tf) VALUES (:faq_id, :term_id, :tf)"),
                     [{"faq_id": f, "term_id": term_id[t], "tf": tf} for f, t, tf in rows])
    print(f"Обратный индекс: {len(vocabulary)} терминов, {len(rows)} связей вопрос–термин")


if __name__ == "__main__":
    from database import get_engine
    eng = get_engine()
    load_term_index(eng, pd.read_sql("SELECT faq_id, question FROM faq ORDER BY faq_id", eng))
