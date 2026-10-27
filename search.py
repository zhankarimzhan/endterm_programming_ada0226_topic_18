"""Поиск ответа в FAQ средствами PostgreSQL (pg_trgm) и запись истории вопросов."""
from sqlalchemy import text
from sqlalchemy.engine import Engine

METHOD_NAME = "pg_trgm"

# word_similarity: насколько запрос похож на какой-либо фрагмент вопроса из FAQ
# (короткий запрос не штрафуется за то, что вопрос в базе длиннее)
SEARCH_SQL = text("""
    SELECT faq_id, question, answer,
           word_similarity(lower(:q), lower(question)) AS score
    FROM faq
    ORDER BY score DESC
    LIMIT :k
""")

LOG_SQL = text("""
    INSERT INTO chat_log (user_query, method_id, faq_id, score)
    SELECT :q, method_id, :faq_id, :score FROM methods WHERE name = :method
""")


def search_faq(engine: Engine, query: str, k: int = 3) -> list[dict]:
    """Возвращает k самых похожих вопросов FAQ с ответами и оценкой сходства (0..1)."""
    with engine.connect() as conn:
        rows = conn.execute(SEARCH_SQL, {"q": query, "k": k}).mappings().all()
    return [dict(r) for r in rows]


def log_question(engine: Engine, query: str, faq_id: int | None, score: float | None) -> None:
    """Сохраняет вопрос пользователя и найденный ответ в chat_log (без данных о пользователе)."""
    with engine.begin() as conn:
        conn.execute(LOG_SQL, {"q": query, "faq_id": faq_id, "score": score, "method": METHOD_NAME})


if __name__ == "__main__":
    from database import get_engine
    eng = get_engine()
    for q in ["как поступить в аиту", "сколько стоит обучение", "какие предметы ент для информационной безопасности"]:
        best = search_faq(eng, q, k=1)[0]
        print(f"{q!r} -> [{best['score']:.2f}] {best['question']}")
