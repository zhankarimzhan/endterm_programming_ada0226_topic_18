"""Подготовка методов поиска по FAQ из базы, сравнение методов на одном запросе и запись в нормализованную схему:
requests (вопрос) -> method_runs (запуск метода, время) -> candidates (топ-k ответов метода); feedback (оценки)."""
import logging
import time
import uuid

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from methods import METHOD_CLASSES, SimilarityMethod

# Регистрация метода, его порога и ресурсов (время подготовки, память)
REGISTER_SQL = text("""
    INSERT INTO methods (name, preprocessing, title, min_score, fit_seconds, memory_mb, updated_at)
    VALUES (:name, :prep, :title, :min_score, :fit, :mem, now())
    ON CONFLICT (name, preprocessing) DO UPDATE
    SET title = EXCLUDED.title, min_score = EXCLUDED.min_score, fit_seconds = EXCLUDED.fit_seconds,
        memory_mb = EXCLUDED.memory_mb, updated_at = EXCLUDED.updated_at
""")

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

FEEDBACK_SQL = text("""
    INSERT INTO feedback (request_id, faq_id, helpful) VALUES (:rid, :faq_id, :helpful)
    ON CONFLICT (request_id, faq_id) DO UPDATE SET helpful = EXCLUDED.helpful, created_at = now()
""")

UNANSWERED_SQL = text("SELECT reason FROM v_unanswered WHERE request_id = :rid")


def load_faq(engine: Engine) -> pd.DataFrame:
    """Вопросы и ответы из таблицы faq."""
    return pd.read_sql("SELECT faq_id, question, answer FROM faq ORDER BY faq_id", engine)


def register_methods(engine: Engine, methods: dict[str, SimilarityMethod]) -> None:
    """Записывает методы, их пороги и ресурсы в таблицу methods."""
    with engine.begin() as conn:
        for m in methods.values():
            conn.execute(REGISTER_SQL, {"name": m.name, "prep": m.preprocessing, "title": m.title,
                                        "min_score": m.min_score, "fit": m.fit_seconds, "mem": m.memory})


def build_methods(engine: Engine, names: list[str] | None = None) -> dict[str, SimilarityMethod]:
    """Создаёт и обучает методы, замеряя время подготовки и память.
    Метод, который не удалось подготовить (например, нет сети для модели), пропускается."""
    faq = load_faq(engine)
    methods = {}
    for name in names or METHOD_CLASSES:
        start = time.perf_counter()
        try:
            m = METHOD_CLASSES[name](engine=engine).fit(faq)
            m.fit_seconds = time.perf_counter() - start
            m.memory = m.memory_mb()
        except Exception:
            logging.exception("Метод %s не удалось подготовить, он будет недоступен", name)
            continue
        methods[name] = m
        logging.info("Метод %s готов за %.1f с, память %.1f МБ", name, m.fit_seconds, m.memory)
    register_methods(engine, methods)
    return methods


def timed_search(method: SimilarityMethod, query: str, k: int = 3) -> tuple[list[dict], float]:
    """Поиск с замером времени; возвращает (результаты, миллисекунды)."""
    start = time.perf_counter()
    results = method.search(query, k)
    return results, (time.perf_counter() - start) * 1000


def compare_all(methods: dict[str, SimilarityMethod], query: str, k: int = 3) -> list[dict]:
    """Запускает все методы на одном запросе. Для каждого метода: результаты, лучший ответ, время, прошёл ли порог."""
    rows = []
    for m in methods.values():
        try:
            results, ms = timed_search(m, query, k)
        except Exception:
            logging.exception("Ошибка поиска (%s)", m.name)
            continue
        best = results[0] if results else None
        rows.append({"method": m, "results": results, "best": best, "latency_ms": ms,
                     "found": best is not None and best["score"] >= m.min_score})
    return rows


def _log_run(conn: Connection, request_id: str, method: SimilarityMethod, results: list[dict], latency_ms: float) -> None:
    """Запуск метода и его топ-k кандидатов."""
    method_id = conn.execute(RUN_SQL, {"rid": request_id, "latency": latency_ms,
                                       "name": method.name, "prep": method.preprocessing}).scalar()
    if method_id is None:
        return
    conn.execute(CANDIDATE_SQL, [{"rid": request_id, "method_id": method_id, "rank": rank,
                                  "faq_id": r["faq_id"], "score": r["score"]}
                                 for rank, r in enumerate(results, start=1)])


def log_comparison(engine: Engine, query: str, rows: list[dict]) -> str:
    """Сохраняет запрос и ответы всех методов (режим сравнения); возвращает request_id."""
    request_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(REQUEST_SQL, {"rid": request_id, "q": query, "mode": "compare"})
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


def save_feedback(engine: Engine, request_id: str, faq_id: int, helpful: bool) -> None:
    """Оценка пользователя: подошёл ли ответ faq_id на запрос. Засчитывается методам, вернувшим этот ответ
    (а при 👍 остальные методы этого запроса считаются ошибившимися) — см. представление v_method_answers."""
    with engine.begin() as conn:
        conn.execute(FEEDBACK_SQL, {"rid": request_id, "faq_id": faq_id, "helpful": helpful})


def unanswered_reason(engine: Engine, request_id: str) -> str | None:
    """'not_found' / 'bad_answer', если запрос остался без подходящего ответа (представление v_unanswered)."""
    with engine.connect() as conn:
        return conn.execute(UNANSWERED_SQL, {"rid": request_id}).scalar()


if __name__ == "__main__":
    from database import get_engine
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    all_methods = build_methods(get_engine())
    for q in ["как поступить в аиту", "сколько стоит обучение", "есть ли общага"]:
        print(f"\n{q!r}")
        for r in compare_all(all_methods, q, k=1):
            mark = "" if r["found"] else "  (ниже порога)"
            print(f"  {r['method'].title:<22} [{r['best']['score']:.2f}] {r['latency_ms']:6.1f} мс  "
                  f"{r['best']['question'][:60]}{mark}")
