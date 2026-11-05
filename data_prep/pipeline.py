"""Подготовка данных целиком: скачивание → очистка → data/faq.parquet и таблица faq → обратный индекс.
Запуск: python -m data_prep.pipeline"""
from data_prep.cleaning import clean, print_summary
from data_prep.download import CLEAN_PATH, download_raw
from data_prep.storage import load_faq, load_to_db
from data_prep.term_index import load_term_index
from db import check_connection, get_engine


def main() -> None:
    engine = get_engine()
    if not check_connection(engine):
        return
    raw = download_raw()                     # шаг 1
    faq = clean(raw)                         # шаг 2
    print_summary(raw, faq)
    faq.to_parquet(CLEAN_PATH, index=False)
    load_to_db(faq, engine)                  # шаг 3
    # шаг 4: обратный индекс строится по тому, что фактически лежит в базе
    load_term_index(engine, load_faq(engine))


if __name__ == "__main__":
    main()
