"""Оценка методов на тестовых вопросах: Precision@1, Precision@3, MRR, время, память; сравнение стемминга и лемматизации.
Два набора (TEST_SETS):
  base         data/test_queries.csv — 40 перефраз разных вопросов FAQ;
  paraphrases  data/paraphrases.csv  — 10 вопросов, по каждому формулировки разных типов (сленг, синоним, опечатка,
               транслит, английский, зеркальные) — метрики по типам формулировок и темам (представление v_test_hits).
Результаты -> test_queries, test_acceptable, runs (по прогону на метод и набор), predictions.
Запускается из init_project.py (первичный запуск проекта) или отдельно: python -m analytics.evaluation [--force]."""
import argparse
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from methods import METHOD_CLASSES, SimilarityMethod
from search import load_faq, register_methods, timed_search

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TEST_SETS = {"base": DATA_DIR / "test_queries.csv", "paraphrases": DATA_DIR / "paraphrases.csv"}
K = 3                                              # глубина поиска: Precision@1, Precision@3, MRR по топ-3
LEMMA_VARIANTS = ("rule_based", "bow", "tfidf")    # методы с предобработкой — сравниваем стемминг и лемматизацию

RUN_SQL = text("""
    INSERT INTO runs (method_id, test_set, p_at_1, p_at_3, mrr, time_ms, memory_mb)
    SELECT method_id, :test_set, :p1, :p3, :mrr, :ms, :mem FROM methods WHERE name = :name AND preprocessing = :prep
    RETURNING run_id
""")
PREDICTION_SQL = text("""
    INSERT INTO predictions (run_id, query_id, rank, faq_id, score) VALUES (:run_id, :query_id, :rank, :faq_id, :score)
""")
QUERY_SQL = text("""
    INSERT INTO test_queries (text, true_faq_id, test_set, query_type, topic)
    VALUES (:q, :fid, :test_set, :type, :topic) RETURNING query_id
""")
ACCEPTABLE_SQL = text("INSERT INTO test_acceptable (query_id, faq_id) VALUES (:query_id, :faq_id)")


def norm(s: str) -> str:
    return " ".join(str(s).split())


def load_test_set(engine: Engine, test_set: str) -> pd.DataFrame:
    """Тестовые вопросы набора: query, true_faq_id, acceptable (множество верных faq_id), query_type, topic.
    base: колонки query, true_question (вопрос FAQ ищется по тексту);
    paraphrases: query, true_faq_id, also_correct (через «;»), type, group.
    Верными считаются также вопросы FAQ с тем же текстом ответа (дубликаты)."""
    path = TEST_SETS[test_set]
    tests = pd.read_csv(path, dtype=str).fillna("")
    faq = load_faq(engine)
    answer_of = {int(i): norm(a) for i, a in zip(faq["faq_id"], faq["answer"])}
    if "true_question" in tests:
        by_question = {norm(q): int(i) for i, q in zip(faq["faq_id"], faq["question"])}
        missing = [q for q in tests["true_question"] if norm(q) not in by_question]
        if missing:
            raise ValueError(f"Вопросы из {path.name} не найдены в FAQ: {missing}")
        tests["true_faq_id"] = tests["true_question"].map(lambda q: by_question[norm(q)])
    tests["true_faq_id"] = tests["true_faq_id"].astype(int)
    also = tests.get("also_correct", pd.Series("", index=tests.index))
    tests["acceptable"] = [
        {i for i, a in answer_of.items() if a in {answer_of[f] for f in ids}}
        for ids in ({fid} | {int(x) for x in extra.split(";") if x} for fid, extra in zip(tests["true_faq_id"], also))]
    unknown = {f for ids in tests["acceptable"] for f in ids} - set(answer_of) | set(tests["true_faq_id"]) - set(answer_of)
    if unknown:
        raise ValueError(f"В {path.name} есть faq_id, которых нет в FAQ: {sorted(unknown)}")
    tests["query_type"] = tests.get("type", pd.Series("", index=tests.index))
    tests["topic"] = tests.get("group", pd.Series("", index=tests.index))
    tests["test_set"] = test_set
    return tests[["query", "true_faq_id", "acceptable", "query_type", "topic", "test_set"]]


def store_test_queries(engine: Engine, tests: pd.DataFrame) -> pd.DataFrame:
    """Записывает вопросы всех наборов и их допустимые ответы (предыдущие наборы и оценки удаляются)."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE predictions, runs, test_acceptable, test_queries RESTART IDENTITY"))
        ids = []
        for r in tests.itertuples():
            query_id = conn.execute(QUERY_SQL, {"q": r.query, "fid": int(r.true_faq_id), "test_set": r.test_set,
                                                "type": r.query_type or None, "topic": r.topic or None}).scalar()
            conn.execute(ACCEPTABLE_SQL, [{"query_id": query_id, "faq_id": f} for f in sorted(r.acceptable)])
            ids.append(query_id)
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
    metrics = {"test_set": tests["test_set"].iat[0], "method": method.title, "name": method.name,
               "preprocessing": method.preprocessing,
               "p_at_1": hits1 / n, "p_at_3": hits3 / n, "mrr": rr / n,
               "time_ms": total_ms / n, "memory_mb": method.memory}
    return metrics, predictions


def save_run(engine: Engine, method: SimilarityMethod, metrics: dict, predictions: list[dict]) -> None:
    with engine.begin() as conn:
        run_id = conn.execute(RUN_SQL, {"test_set": metrics["test_set"], "p1": metrics["p_at_1"], "p3": metrics["p_at_3"], "mrr": metrics["mrr"],
                                        "ms": metrics["time_ms"], "mem": metrics["memory_mb"],
                                        "name": method.name, "prep": method.preprocessing}).scalar()
        conn.execute(PREDICTION_SQL, [dict(p, run_id=run_id) for p in predictions])


def evaluation_done(engine: Engine) -> bool:
    """Есть прогоны по всем наборам из TEST_SETS (новый набор — повод пересчитать)."""
    with engine.connect() as conn:
        done = set(conn.execute(text("SELECT DISTINCT test_set FROM runs")).scalars())
    return set(TEST_SETS) <= done


def run_evaluation(engine: Engine, methods: dict[str, SimilarityMethod], force: bool = False) -> pd.DataFrame | None:
    """Полный прогон тестовых вопросов. Если оценка уже есть и force=False — ничего не делает."""
    if evaluation_done(engine) and not force:
        print("Оценка на тестовых вопросах уже выполнена (повторить: --force)")
        return None
    tests = store_test_queries(engine, pd.concat([load_test_set(engine, name) for name in TEST_SETS], ignore_index=True))
    print("Тестовых вопросов: " + ", ".join(f"{name} — {n}" for name, n in tests["test_set"].value_counts().items()))
    rows = []
    for m in list(methods.values()) + list(build_lemma_variants(engine, methods).values()):
        for _, part in tests.groupby("test_set", sort=False):
            metrics, predictions = evaluate_method(m, part)
            save_run(engine, m, metrics, predictions)
            rows.append(metrics)
    return pd.DataFrame(rows).sort_values(["test_set", "mrr", "time_ms"], ascending=[True, False, True])


def format_results(df: pd.DataFrame) -> str:
    show = df[["test_set", "method", "preprocessing", "p_at_1", "p_at_3", "mrr", "time_ms", "memory_mb"]].copy()
    show[["p_at_1", "p_at_3", "mrr"]] = show[["p_at_1", "p_at_3", "mrr"]].round(3)
    show[["time_ms", "memory_mb"]] = show[["time_ms", "memory_mb"]].round(2)
    return show.to_string(index=False)


if __name__ == "__main__":
    from db import check_connection, get_engine
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
