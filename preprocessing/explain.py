"""Разбор текста по шагам предобработки — что видит каждый метод (для API и дашборда)."""
from preprocessing.lemmatization import lemmatize
from preprocessing.normalize import normalize, tokenize
from preprocessing.stemming import stem
from preprocessing.stopwords import STOPWORDS


def explain(text: str) -> dict:
    """Результат каждого шага: нормализация, слова, стоп-слова, стеммы, леммы, замены правил rule-based."""
    from methods.rule_based import apply_rules            # правила — часть метода, а не общей предобработки
    tokens = tokenize(text)
    kept = [t for t in tokens if t not in STOPWORDS]
    ruled = apply_rules(text)
    return {
        "normalized": normalize(text),                             # шаг 1
        "tokens": tokens,                                          # шаг 2
        "stopwords": [t for t in tokens if t in STOPWORDS],        # шаг 3: удалённые
        "kept": kept,
        "stems": [stem(t) for t in kept],                          # шаг 4а
        "lemmas": [lemmatize(t) for t in kept],                    # шаг 4б
        "rules": {"text": ruled, "changed": ruled != normalize(text)},
    }
