"""Подготовка данных FAQ: скачивание → очистка → загрузка в PostgreSQL → обратный индекс терминов.

  download.py    1. CSV с Hugging Face (или сохранённая копия data/raw.parquet)
  cleaning.py    2. очистка: пробелы, пустые строки, копии заголовка, дубликаты
  storage.py     3. запись в таблицу faq
  term_index.py  4. обратный индекс terms / faq_terms (для SQL-аналитики)
  pipeline.py    все шаги подряд: python -m data_prep.pipeline
"""
