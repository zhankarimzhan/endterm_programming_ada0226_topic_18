"""Embeddings: предобученная модель sentence-transformers переводит смысл фразы в вектор + косинусное сходство.

Алгоритм
  Подготовка (fit):
    1. Загрузка модели paraphrase-multilingual-MiniLM-L12-v2 (обучена находить перефразы, понимает русский).
    2. Каждый вопрос FAQ как есть (без стоп-слов и стемминга — модель сама разбирает текст)
       → вектор из 384 чисел; векторы нормируются до длины 1.
  Поиск (scores):
    1. Запрос → вектор той же моделью.
    2. Сходство с каждым вопросом: скалярное произведение векторов
       (для векторов длины 1 оно равно косинусному сходству).
"""
import numpy as np

from methods.base import SimilarityMethod

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class EmbeddingsMethod(SimilarityMethod):
    name = "embeddings"
    title = "Embeddings (MiniLM)"
    preprocessing = "none"     # модель сама работает с исходным текстом
    min_score = 0.5

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Тексты → нормированные векторы."""
        return self.model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)

    def _fit(self, questions: list[str]) -> None:
        from sentence_transformers import SentenceTransformer   # тяжёлый импорт — только при использовании
        self.model = SentenceTransformer(MODEL_NAME, device="cpu")   # шаг 1
        self.matrix = self._encode(questions)                        # шаг 2

    def memory_mb(self) -> float:
        """Векторы вопросов + веса модели, МБ."""
        params = sum(p.numel() * p.element_size() for p in self.model.parameters())
        return (self.matrix.nbytes + params) / 2 ** 20

    def scores(self, query: str) -> np.ndarray:
        q = self._encode([query])[0]   # шаг 1
        return self.matrix @ q         # шаг 2
