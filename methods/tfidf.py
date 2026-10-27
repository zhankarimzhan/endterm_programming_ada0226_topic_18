"""TF-IDF: вес слова = частота в вопросе × редкость в FAQ; слова и биграммы + косинусное сходство."""
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
        self.vectorizer = TfidfVectorizer(token_pattern=r"\S+", ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform([preprocess_text(q, self.preprocessing) for q in questions])

    def scores(self, query: str) -> np.ndarray:
        q = self.vectorizer.transform([preprocess_text(query, self.preprocessing)])
        return cosine_similarity(q, self.matrix).ravel()
