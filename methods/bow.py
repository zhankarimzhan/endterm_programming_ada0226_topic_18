"""Bag of Words: число вхождений слов (CountVectorizer) + косинусное сходство."""
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
        self.vectorizer = CountVectorizer(token_pattern=r"\S+")
        self.matrix = self.vectorizer.fit_transform([preprocess_text(q, self.preprocessing) for q in questions])

    def scores(self, query: str) -> np.ndarray:
        q = self.vectorizer.transform([preprocess_text(query, self.preprocessing)])
        return cosine_similarity(q, self.matrix).ravel()
