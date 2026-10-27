"""Подключение к PostgreSQL и выполнение SQL-запросов."""
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

load_dotenv(Path(__file__).parent / ".env")


def get_engine() -> Engine:
    """Создаёт подключение к базе по параметрам из .env."""
    url = (f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
           f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5433')}/{os.getenv('POSTGRES_DB')}")
    return create_engine(url)


def check_connection(engine: Engine) -> bool:
    """Проверяет, что база доступна; при ошибке подсказывает, как поднять контейнер."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        print("Нет подключения к PostgreSQL. Запустите базу: docker-compose up -d")
        return False


def list_tables(engine: Engine) -> list:
    """Список таблиц в схеме public."""
    query = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
    return pd.read_sql(query, engine)["table_name"].tolist()


def save_dataframe(df: pd.DataFrame, table: str, engine: Engine) -> None:
    """Дописывает DataFrame в существующую таблицу."""
    df.to_sql(table, engine, if_exists="append", index=False)


def run_query(sql: str, engine: Engine, params: dict | None = None) -> pd.DataFrame:
    """Выполняет SELECT и возвращает результат как DataFrame."""
    return pd.read_sql(text(sql), engine, params=params)


if __name__ == "__main__":
    eng = get_engine()
    if check_connection(eng):
        print("Подключение есть. Таблицы:", list_tables(eng))
