"""Шаг 1: скачивание датасета AITU Admissions FAQ."""
from pathlib import Path

import pandas as pd

DATA_URL = ("https://huggingface.co/datasets/Arailym-tleubayeva/AITUAdmissionsGuideDataset/"
            "resolve/main/QA_addmissionAitu.csv")
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
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
