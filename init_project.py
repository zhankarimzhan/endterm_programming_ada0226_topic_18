"""Первичная инициализация проекта — запускается один раз после `docker-compose up -d`:
  1. FAQ: скачивание, очистка, загрузка в PostgreSQL и обратный индекс терминов (если база пуста);
  2. тестовые вопросы (data/test_queries.csv): прогон всех методов, метрики Precision@1/3, MRR, время, память
     (таблицы runs, predictions), сравнение стемминга и лемматизации, запросы в статистику бота (режим 'test').
Повторный запуск ничего не дублирует. --force — пересчитать оценку на тестовых вопросах заново.
Запуск: python init_project.py [--force]"""
import argparse
import logging

from sqlalchemy import text

from analytics.evaluation import format_results, run_evaluation
from data_prep import pipeline as data_pipeline
from data_prep.storage import load_faq
from data_prep.term_index import load_term_index
from db import check_connection, get_engine
from search import build_methods


def table_is_empty(engine, table: str) -> bool:
    with engine.connect() as conn:
        return not conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()


def main() -> None:
    parser = argparse.ArgumentParser(description="Первичная инициализация проекта")
    parser.add_argument("--force", action="store_true", help="пересчитать оценку на тестовых вопросах")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    engine = get_engine()
    if not check_connection(engine):
        return

    print("1/3 Данные FAQ")
    if table_is_empty(engine, "faq"):
        data_pipeline.main()
    elif table_is_empty(engine, "terms"):
        load_term_index(engine, load_faq(engine))
    else:
        print("FAQ и обратный индекс уже загружены")

    print("2/3 Методы поиска")
    methods = build_methods(engine)
    print("Готовы:", ", ".join(m.title for m in methods.values()))

    print("3/3 Тестовые вопросы")
    result = run_evaluation(engine, methods, force=args.force)
    if result is not None:
        print(format_results(result))
    print("Готово. Запуск всего проекта (API, дашборд, туннель для Telegram, бот): ./run.sh")


if __name__ == "__main__":
    main()
