"""Шаг 3: запись очищенного FAQ в PostgreSQL."""
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


def load_faq(engine: Engine) -> pd.DataFrame:
    """Вопросы и ответы из таблицы faq."""
    return pd.read_sql("SELECT faq_id, question, answer FROM faq ORDER BY faq_id", engine)


def load_to_db(df: pd.DataFrame, engine: Engine, replace: bool = False) -> None:
    """Записывает FAQ в таблицу faq. Если данные уже есть и replace=False — ничего не делает."""
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM faq")).scalar()
        if count and not replace:
            print(f"В таблице faq уже {count} записей, загрузка пропущена (replace=True для перезаписи)")
            return
        conn.execute(text("TRUNCATE faq CASCADE"))
        df[["faq_id", "question", "answer", "raw_label"]].to_sql("faq", conn, if_exists="append", index=False)
    print(f"В таблицу faq записано {len(df)} строк")
