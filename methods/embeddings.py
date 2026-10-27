"""Embeddings: предобученная модель sentence-transformers переводит смысл фразы в вектор + косинусное сходство."""
import numpy as np

from methods.base import SimilarityMethod

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class EmbeddingsMethod(SimilarityMethod):
    name = "embeddings"
    title = "Embeddings (MiniLM)"
    preprocessing = "none"     # модель сама работает с исходным текстом
    min_score = 0.5

    def _fit(self, questions: list[str]) -> None:
        from sentence_transformers import SentenceTransformer   # тяжёлый импорт — только при использовании
        self.model = SentenceTransformer(MODEL_NAME, device="cpu")
        self.matrix = self.model.encode(questions, normalize_embeddings=True, batch_size=64, show_progress_bar=False)

    def memory_mb(self) -> float:
        """Векторы вопросов + веса модели, МБ."""
        params = sum(p.numel() * p.element_size() for p in self.model.parameters())
        return (self.matrix.nbytes + params) / 2 ** 20

    def scores(self, query: str) -> np.ndarray:
        q = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        return self.matrix @ q   # векторы нормированы, поэтому скалярное произведение = косинусное сходство
