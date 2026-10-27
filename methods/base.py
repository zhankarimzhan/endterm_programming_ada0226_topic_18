"""Общий интерфейс методов поиска похожего вопроса."""
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class SimilarityMethod(ABC):
    """Метод поиска: fit() готовит индекс по вопросам FAQ, scores() даёт сходство запроса с каждым вопросом."""

    name: str = ""            # короткое имя (в базе и в коде)
    title: str = ""           # название для пользователя
    preprocessing: str = ""   # какая предобработка используется
    min_score: float = 0.3    # ниже этого порога ответ считается ненайденным

    def __init__(self, engine=None):
        self.engine = engine
        self.faq: pd.DataFrame | None = None

    def fit(self, faq: pd.DataFrame) -> "SimilarityMethod":
        """Запоминает FAQ и строит индекс."""
        self.faq = faq.reset_index(drop=True)
        self._fit(self.faq["question"].tolist())
        return self

    @abstractmethod
    def _fit(self, questions: list[str]) -> None:
        """Построение индекса по текстам вопросов."""

    @abstractmethod
    def scores(self, query: str) -> np.ndarray:
        """Сходство запроса с каждым вопросом FAQ (массив длины len(faq))."""

    def search(self, query: str, k: int = 3) -> list[dict]:
        """k самых похожих вопросов с ответами и оценкой сходства."""
        s = self.scores(query)
        top = np.argsort(-s, kind="stable")[:k]
        return [{"faq_id": int(self.faq.at[i, "faq_id"]), "question": self.faq.at[i, "question"],
                 "answer": self.faq.at[i, "answer"], "score": float(s[i])} for i in top]
