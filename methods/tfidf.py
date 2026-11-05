"""TF-IDF: вес слова = частота в вопросе × редкость в FAQ; слова и биграммы + косинусное сходство.

Алгоритм
  Подготовка (fit):
    1. Предобработка каждого вопроса FAQ: токены → без стоп-слов → стеммы.
    2. Словарь: отдельные слова и биграммы (пары соседних слов: «стоимост обучен»).
    3. TF: 1 + log(число вхождений в вопросе) — повтор слова даёт всё меньший прирост.
    4. IDF: log((1 + N) / (1 + df)) + 1, где N — вопросов в FAQ, df — в скольких вопросах есть термин;
       частые слова («аиту», «как») получают малый вес, редкие — большой.
    5. Вес = TF × IDF; вектор каждого вопроса нормируется по длине.
  Поиск (scores):
    1. Та же предобработка запроса.
    2. Вектор запроса с теми же IDF (терминов, которых нет в FAQ, не учитываем).
    3. Косинусное сходство запроса с каждым вопросом, от 0 до 1.
"""
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from methods.base import SimilarityMethod
from preprocessing import preprocess_text


class TfidfMethod(SimilarityMethod):
    name = "tfidf"
    title = "TF-IDF"
    preprocessing = "stem"
    min_score = 0.3

    def _fit(self, questions: list[str]) -> None:
        # шаг 1: предобработка
        docs = [preprocess_text(q, self.preprocessing) for q in questions]
        # шаги 2–5: ngram_range=(1, 2) — слова и биграммы, sublinear_tf — логарифмический TF
        self.vectorizer = TfidfVectorizer(token_pattern=r"\S+", ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(docs)

    def scores(self, query: str) -> np.ndarray:
        q = self.vectorizer.transform([preprocess_text(query, self.preprocessing)])   # шаги 1–2
        return cosine_similarity(q, self.matrix).ravel()                               # шаг 3
