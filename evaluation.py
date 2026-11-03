"""Оценка методов на тестовых вопросах (data/test_queries.csv): Precision@1, Precision@3, MRR, время, память;
сравнение стемминга и лемматизации. Результаты -> runs / predictions.
Тестовые вопросы также записываются как запросы в режиме 'test' с 👍 правильному ответу —
чтобы попасть в статистику бота, дашборд и SQL-аналитику.
Запускается из init_project.py (первичный запуск проекта) или отдельно: python evaluation.py [--force]."""
import argparse
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from methods import METHOD_CLASSES, SimilarityMethod
from search import compare_all, load_faq, log_comparison, register_methods, save_feedback, timed_search

TEST_PATH = Path(__file__).parent / "data" / "test_queries.csv"
K = 3                                              # глубина поиска: Precision@1, Precision@3, MRR по топ-3
LEMMA_VARIANTS = ("rule_based", "bow", "tfidf")    # методы с предобработкой — сравниваем стемминг и лемматизацию

RUN_SQL = text("""
    INSERT INTO runs (method_id, p_at_1, p_at_3, mrr, time_ms, memory_mb)
    SELECT method_id, :p1, :p3, :mrr, :ms, :mem FROM methods WHERE name = :name AND preprocessing = :prep
    RETURNING run_id
""")
PREDICTION_SQL = text("""
    INSERT INTO predictions (run_id, query_id, rank, faq_id, score) VALUES (:run_id, :query_id, :rank, :faq_id, :score)
""")


def norm(s: str) -> str:
    return " ".join(str(s).split())


def load_test_set(engine: Engine, path: Path = TEST_PATH) -> pd.DataFrame:
    """Тестовые вопросы с правильным faq_id и множеством допустимых ответов
    (вопросы FAQ с тем же текстом ответа — дубликаты тоже считаются верными)."""
    tests = pd.read_csv(path)
    faq = load_faq(engine)
    by_question = {norm(q): int(i) for i, q in zip(faq["faq_id"], faq["question"])}
    missing = [q for q in tests["true_question"] if norm(q) not in by_question]
    if missing:
        raise ValueError(f"Вопросы из {path.name} не найдены в FAQ: {missing}")
    answer_of = {int(i): norm(a) for i, a in zip(faq["faq_id"], faq["answer"])}
    tests["true_faq_id"] = tests["true_question"].map(lambda q: by_question[norm(q)])
    tests["acceptable"] = tests["true_faq_id"].map(
        lambda fid: {i for i, a in answer_of.items() if a == answer_of[fid]})
    return tests


def store_test_queries(engine: Engine, tests: pd.DataFrame) -> pd.DataFrame:
    """Записывает вопросы в test_queries (предыдущий набор и его оценки удаляются)."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE predictions, runs, test_queries RESTART IDENTITY"))
        ids = [conn.execute(text("INSERT INTO test_queries (text, true_faq_id) VALUES (:q, :fid) RETURNING query_id"),
                            {"q": r.query, "fid": int(r.true_faq_id)}).scalar() for r in tests.itertuples()]
    return tests.assign(query_id=ids)


def build_lemma_variants(engine: Engine, methods: dict[str, SimilarityMethod]) -> dict[str, SimilarityMethod]:
    """Те же методы, но с лемматизацией вместо стемминга (для сравнения предобработки)."""
    faq = load_faq(engine)
    variants = {}
    for name in LEMMA_VARIANTS:
        if name not in methods:
            continue
        m = METHOD_CLASSES[name](engine=engine)
        m.preprocessing = "lemma"
        m.title = f"{m.title} · лемматизация"
        start = pd.Timestamp.now()
        m.fit(faq)
        m.fit_seconds = (pd.Timestamp.now() - start).total_seconds()
        m.memory = m.memory_mb()
        variants[f"{name}:lemma"] = m
    register_methods(engine, variants)
    return variants


def evaluate_method(method: SimilarityMethod, tests: pd.DataFrame) -> tuple[dict, list[dict]]:
    """Precision@1, Precision@3, MRR, среднее время поиска и топ-k предсказания метода."""
    hits1 = hits3 = rr = total_ms = 0.0
    predictions = []
    for t in tests.itertuples():
        results, ms = timed_search(method, t.query, K)
        total_ms += ms
        ranks = [rank for rank, r in enumerate(results, start=1) if r["faq_id"] in t.acceptable]
        first = ranks[0] if ranks else None
        hits1 += first == 1
        hits3 += first is not None and first <= 3
        rr += 1 / first if first else 0
        predictions += [{"query_id": int(t.query_id), "rank": rank, "faq_id": r["faq_id"], "score": r["score"]}
                        for rank, r in enumerate(results, start=1)]
    n = len(tests)
    metrics = {"method": method.title, "name": method.name, "preprocessing": method.preprocessing,
               "p_at_1": hits1 / n, "p_at_3": hits3 / n, "mrr": rr / n,
               "time_ms": total_ms / n, "memory_mb": method.memory}
    return metrics, predictions


def save_run(engine: Engine, method: SimilarityMethod, metrics: dict, predictions: list[dict]) -> None:
    with engine.begin() as conn:
        run_id = conn.execute(RUN_SQL, {"p1": metrics["p_at_1"], "p3": metrics["p_at_3"], "mrr": metrics["mrr"],
                                        "ms": metrics["time_ms"], "mem": metrics["memory_mb"],
                                        "name": method.name, "prep": method.preprocessing}).scalar()
        conn.execute(PREDICTION_SQL, [dict(p, run_id=run_id) for p in predictions])


def push_to_bot_stats(engine: Engine, methods: dict[str, SimilarityMethod], tests: pd.DataFrame) -> int:
    """Отправляет тестовые вопросы «в бота»: запрос в режиме 'test' с ответами всех методов
    и 👍 правильному ответу (и его дубликатам, если метод вернул дубликат)."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM requests WHERE mode = 'test'"))
    for t in tests.itertuples():
        rows = compare_all(methods, t.query, K)
        request_id = log_comparison(engine, t.query, rows, mode="test")
        approved = {t.true_faq_id} | {r["best"]["faq_id"] for r in rows if r["best"] and r["best"]["faq_id"] in t.acceptable}
        for faq_id in approved:
            save_feedback(engine, request_id, int(faq_id), True)
    return len(tests)


def evaluation_done(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text("SELECT EXISTS (SELECT 1 FROM runs)")).scalar())


def run_evaluation(engine: Engine, methods: dict[str, SimilarityMethod], force: bool = False) -> pd.DataFrame | None:
    """Полный прогон тестовых вопросов. Если оценка уже есть и force=False — ничего не делает."""
    if evaluation_done(engine) and not force:
        print("Оценка на тестовых вопросах уже выполнена (повторить: --force)")
        return None
    tests = store_test_queries(engine, load_test_set(engine))
    print(f"Тестовых вопросов: {len(tests)}")
    rows = []
    for m in list(methods.values()) + list(build_lemma_variants(engine, methods).values()):
        metrics, predictions = evaluate_method(m, tests)
        save_run(engine, m, metrics, predictions)
        rows.append(metrics)
    print(f"В статистику бота записано тестовых запросов: {push_to_bot_stats(engine, methods, tests)}")
    return pd.DataFrame(rows).sort_values(["mrr", "time_ms"], ascending=[False, True])


def format_results(df: pd.DataFrame) -> str:
    show = df[["method", "preprocessing", "p_at_1", "p_at_3", "mrr", "time_ms", "memory_mb"]].copy()
    show[["p_at_1", "p_at_3", "mrr"]] = show[["p_at_1", "p_at_3", "mrr"]].round(3)
    show[["time_ms", "memory_mb"]] = show[["time_ms", "memory_mb"]].round(2)
    return show.to_string(index=False)


if __name__ == "__main__":
    from database import check_connection, get_engine
    from search import build_methods
    parser = argparse.ArgumentParser(description="Оценка методов на тестовых вопросах")
    parser.add_argument("--force", action="store_true", help="пересчитать, даже если оценка уже есть")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    eng = get_engine()
    if check_connection(eng):
        result = run_evaluation(eng, build_methods(eng), force=args.force)
        if result is not None:
            print(format_results(result))
