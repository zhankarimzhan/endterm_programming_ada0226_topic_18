"""Подготовка методов поиска по FAQ из базы и сравнение методов на одном запросе.
Проверка в консоли: python -m search.runner"""
import logging
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine

from data_prep.storage import load_faq
from methods import METHOD_CLASSES, SimilarityMethod

# Регистрация метода, его порога и ресурсов (время подготовки, память)
REGISTER_SQL = text("""
    INSERT INTO methods (name, preprocessing, title, min_score, fit_seconds, memory_mb, updated_at)
    VALUES (:name, :prep, :title, :min_score, :fit, :mem, now())
    ON CONFLICT (name, preprocessing) DO UPDATE
    SET title = EXCLUDED.title, min_score = EXCLUDED.min_score, fit_seconds = EXCLUDED.fit_seconds,
        memory_mb = EXCLUDED.memory_mb, updated_at = EXCLUDED.updated_at
""")


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


if __name__ == "__main__":
    from db import get_engine
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    all_methods = build_methods(get_engine())
    for q in ["как поступить в аиту", "сколько стоит обучение", "есть ли общага"]:
        print(f"\n{q!r}")
        for r in compare_all(all_methods, q, k=1):
            mark = "" if r["found"] else "  (ниже порога)"
            print(f"  {r['method'].title:<22} [{r['best']['score']:.2f}] {r['latency_ms']:6.1f} мс  "
                  f"{r['best']['question'][:60]}{mark}")
