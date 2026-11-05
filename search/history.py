"""Запись истории в нормализованную схему:
requests (вопрос) -> method_runs (запуск метода, время) -> candidates (топ-k ответов метода)."""
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from methods import SimilarityMethod

REQUEST_SQL = text("INSERT INTO requests (request_id, query_text, mode) VALUES (:rid, :q, :mode)")

RUN_SQL = text("""
    INSERT INTO method_runs (request_id, method_id, latency_ms)
    SELECT :rid, method_id, :latency FROM methods WHERE name = :name AND preprocessing = :prep
    RETURNING method_id
""")

CANDIDATE_SQL = text("""
    INSERT INTO candidates (request_id, method_id, rank, faq_id, score)
    VALUES (:rid, :method_id, :rank, :faq_id, :score)
""")


def _log_run(conn: Connection, request_id: str, method: SimilarityMethod, results: list[dict], latency_ms: float) -> None:
    """Запуск метода и его топ-k кандидатов."""
    method_id = conn.execute(RUN_SQL, {"rid": request_id, "latency": latency_ms,
                                       "name": method.name, "prep": method.preprocessing}).scalar()
    if method_id is None:
        return
    conn.execute(CANDIDATE_SQL, [{"rid": request_id, "method_id": method_id, "rank": rank,
                                  "faq_id": r["faq_id"], "score": r["score"]}
                                 for rank, r in enumerate(results, start=1)])


def log_comparison(engine: Engine, query: str, rows: list[dict], mode: str = "compare") -> str:
    """Сохраняет запрос и ответы всех методов (режим сравнения); возвращает request_id."""
    request_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(REQUEST_SQL, {"rid": request_id, "q": query, "mode": mode})
        for r in rows:
            if r["results"]:
                _log_run(conn, request_id, r["method"], r["results"], r["latency_ms"])
    return request_id


def log_single(engine: Engine, query: str, method: SimilarityMethod, results: list[dict], latency_ms: float) -> str:
    """Сохраняет запрос и ответ одного метода; возвращает request_id."""
    request_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(REQUEST_SQL, {"rid": request_id, "q": query, "mode": "single"})
        if results:
            _log_run(conn, request_id, method, results, latency_ms)
    return request_id
