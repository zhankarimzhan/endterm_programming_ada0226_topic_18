"""Bag of Words: число вхождений слов (CountVectorizer) + косинусное сходство.

Алгоритм
  Подготовка (fit):
    1. Предобработка каждого вопроса FAQ: токены → без стоп-слов → стеммы.
    2. Словарь: все различные стеммы из вопросов FAQ.
    3. Матрица «вопрос × слово»: в ячейке — сколько раз слово встречается в вопросе.
  Поиск (scores):
    1. Та же предобработка запроса.
    2. Вектор запроса в том же словаре (слов, которых нет в FAQ, не учитываем).
    3. Косинусное сходство запроса с каждым вопросом: cos = (q · d) / (|q| · |d|), от 0 до 1.
"""
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from methods.base import SimilarityMethod
from preprocessing import preprocess_text


class BowMethod(SimilarityMethod):
    name = "bow"
    title = "Bag of Words"
    preprocessing = "stem"
    min_score = 0.3

    def _fit(self, questions: list[str]) -> None:
        # шаг 1: предобработка
        docs = [preprocess_text(q, self.preprocessing) for q in questions]
        # шаги 2–3: словарь и матрица частот (токены уже разделены пробелами)
        self.vectorizer = CountVectorizer(token_pattern=r"\S+")
        self.matrix = self.vectorizer.fit_transform(docs)

    def scores(self, query: str) -> np.ndarray:
        q = self.vectorizer.transform([preprocess_text(query, self.preprocessing)])   # шаги 1–2
        return cosine_similarity(q, self.matrix).ravel()                               # шаг 3
