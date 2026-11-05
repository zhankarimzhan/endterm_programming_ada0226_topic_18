"""Вопрос → ответы всех методов и разбор: какой ответ выбран, сколько методов за него, разбор текста.
Используется API (POST /api/ask); бот работает с теми же функциями compare_all / log_comparison."""
from collections import defaultdict

from sqlalchemy.engine import Engine

from methods import SimilarityMethod
from preprocessing.explain import explain
from search.history import log_comparison, unanswered_reason
from search.runner import compare_all


def pick_answer(rows: list[dict]) -> dict | None:
    """Итоговый ответ: вопрос FAQ, за который проголосовало больше методов (среди прошедших порог);
    при равенстве — у кого сходство дальше всего превышает порог своего метода."""
    votes = defaultdict(list)
    for r in rows:
        if r["found"]:
            votes[r["best"]["faq_id"]].append(r)
    if not votes:
        return None

    def strength(faq_id):
        return len(votes[faq_id]), max(r["best"]["score"] / r["method"].min_score for r in votes[faq_id])

    faq_id = max(votes, key=strength)
    best = votes[faq_id][0]["best"]
    return {"faq_id": faq_id, "question": best["question"], "answer": best["answer"],
            "methods": [r["method"].name for r in votes[faq_id]], "votes": len(votes[faq_id])}


def method_row(r: dict) -> dict:
    m = r["method"]
    return {"method": m.name, "title": m.title, "preprocessing": m.preprocessing, "min_score": m.min_score,
            "found": r["found"], "score": round(r["best"]["score"], 4) if r["best"] else None,
            "latency_ms": round(r["latency_ms"], 2),
            "results": [{"rank": i, "faq_id": x["faq_id"], "question": x["question"], "answer": x["answer"],
                         "score": round(x["score"], 4), "passes": x["score"] >= m.min_score}
                        for i, x in enumerate(r["results"], start=1)]}


def ask(engine: Engine, methods: dict[str, SimilarityMethod], text: str, k: int = 3,
        names: list[str] | None = None, save: bool = True) -> dict:
    """Прогоняет вопрос через методы (все или names), выбирает ответ и разбирает результат.
    save=True — записать в статистику как запрос в режиме сравнения (виден в /stats и дашборде)."""
    selected = {n: m for n, m in methods.items() if not names or n in names}
    rows = compare_all(selected, text, k)
    found = [r for r in rows if r["found"]]
    request_id = log_comparison(engine, text, rows) if save else None
    answer = pick_answer(rows)
    return {
        "request_id": request_id,
        "query": text,
        "answer": answer,
        "analysis": {
            "text": explain(text),
            "methods_total": len(rows),
            "methods_found": len(found),
            "distinct_answers": len({r["best"]["faq_id"] for r in found}),
            "agreement": round(answer["votes"] / len(found), 2) if answer else None,
            "fastest": min(rows, key=lambda r: r["latency_ms"])["method"].name if rows else None,
            "unanswered_reason": unanswered_reason(engine, request_id) if save else (None if found else "not_found"),
        },
        "methods": [method_row(r) for r in rows],
    }
