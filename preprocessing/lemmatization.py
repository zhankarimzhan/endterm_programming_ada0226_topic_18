"""Шаг 4б: лемматизация — приводит слово к словарной форме по морфологическому словарю. Точнее стемминга, но медленнее."""
from functools import lru_cache

_morph = None


@lru_cache(maxsize=None)
def lemmatize(word: str) -> str:
    """Лемматизация pymorphy3: «поступления» → «поступление»."""
    global _morph
    if _morph is None:
        import pymorphy3                 # словарь грузится только при первом использовании
        _morph = pymorphy3.MorphAnalyzer()
    return _morph.parse(word)[0].normal_form
