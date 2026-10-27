"""Загрузка датасета AITU Admissions FAQ, базовая очистка и запись в PostgreSQL."""
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from database import check_connection, get_engine

DATA_URL = ("https://huggingface.co/datasets/Arailym-tleubayeva/AITUAdmissionsGuideDataset/"
            "resolve/main/QA_addmissionAitu.csv")
DATA_DIR = Path(__file__).parent / "data"
RAW_PATH = DATA_DIR / "raw.parquet"
CLEAN_PATH = DATA_DIR / "faq.parquet"


def download_raw(url: str = DATA_URL) -> pd.DataFrame:
    """Скачивает CSV с Hugging Face; если сети нет — берёт сохранённую копию."""
    try:
        df = pd.read_csv(url, index_col=0)
    except OSError:
        if not RAW_PATH.exists():
            raise
        print("Нет доступа к Hugging Face, используется сохранённая копия:", RAW_PATH)
        return pd.read_parquet(RAW_PATH)
    df = df.rename(columns={"questions": "question", "answers": "answer", "classes": "raw_label"})
    DATA_DIR.mkdir(exist_ok=True)
    df.to_parquet(RAW_PATH, index=False)
    return df


def normalize_text(s: pd.Series) -> pd.Series:
    """Убирает лишние пробелы и переносы строк."""
    return s.fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Базовая очистка: пустые строки, точные дубликаты, повторяющиеся вопросы."""
    df = df.copy()
    for col in ("question", "answer", "raw_label"):
        df[col] = normalize_text(df[col])
    df = df[(df["question"] != "") & (df["answer"] != "")]
    df = df.drop_duplicates(["question", "answer"])
    # Один вопрос с разными ответами: оставляем самый полный (длинный) ответ
    df = (df.assign(answer_len=df["answer"].str.len())
            .sort_values("answer_len", ascending=False)
            .drop_duplicates("question")
            .sort_index()
            .drop(columns="answer_len"))
    df = df.reset_index(drop=True)
    df.insert(0, "faq_id", df.index + 1)
    return df


def print_summary(raw: pd.DataFrame, clean_df: pd.DataFrame) -> None:
    """Короткая сводка: что было и что осталось после очистки."""
    q = normalize_text(raw["question"])
    a = normalize_text(raw["answer"])
    conflicts = pd.DataFrame({"q": q, "a": a}).groupby("q")["a"].nunique()
    print(f"Строк в исходных данных: {len(raw)}")
    print(f"Точных дубликатов (вопрос + ответ): {pd.DataFrame({'q': q, 'a': a}).duplicated().sum()}")
    print(f"Вопросов с разными ответами: {(conflicts > 1).sum()}")
    print(f"Строк без '?' (не похожи на вопрос): {(~q.str.contains(r'\?')).sum()}")
    print(f"Разных меток: {raw['raw_label'].nunique()}")
    print(f"Осталось после очистки: {len(clean_df)}")


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


def main() -> None:
    engine = get_engine()
    if not check_connection(engine):
        return
    raw = download_raw()
    faq = clean(raw)
    print_summary(raw, faq)
    faq.to_parquet(CLEAN_PATH, index=False)
    load_to_db(faq, engine)


if __name__ == "__main__":
    main()
