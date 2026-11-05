"""Шаг 4а: стемминг — отрезает окончание по правилам, без словаря. Быстро, но основа может не быть словом."""
from functools import lru_cache

from nltk.stem.snowball import SnowballStemmer

_stemmer = SnowballStemmer("russian")


@lru_cache(maxsize=None)
def stem(word: str) -> str:
    """Стемминг Snowball: «поступления» → «поступлен»."""
    return _stemmer.stem(word)
