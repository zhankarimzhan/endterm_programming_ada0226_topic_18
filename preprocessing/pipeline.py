"""Полная предобработка текста: шаги 1–4 подряд."""
from preprocessing.lemmatization import lemmatize
from preprocessing.normalize import tokenize
from preprocessing.stemming import stem
from preprocessing.stopwords import remove_stopwords


def preprocess(text: str, mode: str = "stem") -> list[str]:
    """Токены без стоп-слов; mode: 'none' — без нормализации слов, 'stem' — стемминг, 'lemma' — лемматизация."""
    tokens = tokenize(text)              # шаги 1–2: нормализация и разбиение на слова
    tokens = remove_stopwords(tokens)    # шаг 3: стоп-слова
    if mode == "stem":                   # шаг 4: приведение слов к общей форме
        return [stem(t) for t in tokens]
    if mode == "lemma":
        return [lemmatize(t) for t in tokens]
    return tokens


def preprocess_text(text: str, mode: str = "stem") -> str:
    """То же, что preprocess, но строкой (для векторизаторов scikit-learn)."""
    return " ".join(preprocess(text, mode))
