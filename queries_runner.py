"""Выполнение аналитических SQL-запросов из queries.sql и загрузка результатов в pandas.
Запуск: python queries_runner.py — печатает результаты и сохраняет их в results/sql/<ключ>.csv."""
import re
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from database import run_query

QUERIES_PATH = Path(__file__).parent / "queries.sql"
RESULTS_DIR = Path(__file__).parent / "results" / "sql"
HEADER_RE = re.compile(r"^--\s*name:\s*(\w+)\s*\|\s*(.+)$")


def load_queries(path: Path = QUERIES_PATH) -> dict[str, dict]:
    """Разбирает queries.sql: {ключ: {"title": описание, "sql": текст запроса}}."""
    queries, current = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        header = HEADER_RE.match(line)
        if header:
            current = header.group(1)
            queries[current] = {"title": header.group(2).strip(), "sql": ""}
        elif current and not line.lstrip().startswith("--"):
            queries[current]["sql"] += line + "\n"
    for q in queries.values():
        q["sql"] = q["sql"].strip().rstrip(";")
    return queries


def run_named(engine: Engine, name: str, queries: dict | None = None) -> pd.DataFrame:
    """Выполняет запрос по ключу и возвращает DataFrame."""
    queries = queries or load_queries()
    return run_query(queries[name]["sql"], engine)


def run_all(engine: Engine, save: bool = True) -> dict[str, pd.DataFrame]:
    """Выполняет все запросы; при save=True сохраняет результаты в CSV."""
    queries = load_queries()
    results = {}
    if save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for name in queries:
        df = run_named(engine, name, queries)
        results[name] = df
        if save:
            df.to_csv(RESULTS_DIR / f"{name}.csv", index=False)
    return results


if __name__ == "__main__":
    from database import get_engine
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 60)
    eng = get_engine()
    queries = load_queries()
    for name, df in run_all(eng).items():
        print(f"\n=== {name}: {queries[name]['title']} — {len(df)} строк")
        print(df.head(10).to_string(index=False) if not df.empty else "(пусто)")
    print(f"\nРезультаты сохранены в {RESULTS_DIR}")
