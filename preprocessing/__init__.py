"""Обработка текста: нормализация → токенизация → стоп-слова → стемминг или лемматизация.

Шаги лежат в отдельных модулях, preprocess() из pipeline.py собирает их вместе:
  normalize.py      1. нижний регистр, ё → е; 2. разбиение на слова
  stopwords.py      3. удаление стоп-слов (вопросительные слова сохраняются)
  stemming.py       4а. стемминг Snowball («поступления» → «поступлен»)
  lemmatization.py  4б. лемматизация pymorphy3 («поступления» → «поступление»)
  explain.py        результат каждого шага для одного текста (разбор в API)
"""
from preprocessing.lemmatization import lemmatize
from preprocessing.normalize import normalize, tokenize
from preprocessing.pipeline import preprocess, preprocess_text
from preprocessing.stemming import stem
from preprocessing.stopwords import STOPWORDS

__all__ = ["normalize", "tokenize", "STOPWORDS", "stem", "lemmatize", "preprocess", "preprocess_text"]
