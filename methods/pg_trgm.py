"""pg_trgm: сходство по триграммам символов, считается в PostgreSQL (дополнительный SQL-метод)."""
import numpy as np
from sqlalchemy import text

from methods.base import SimilarityMethod

# word_similarity: какая доля триграмм запроса нашлась в каком-либо фрагменте вопроса
SCORES_SQL = text("SELECT faq_id, word_similarity(lower(:q), lower(question)) AS score FROM faq")


class PgTrgmMethod(SimilarityMethod):
    name = "pg_trgm"
    title = "pg_trgm (PostgreSQL)"
    preprocessing = "lower"
    min_score = 0.3

    def _fit(self, questions: list[str]) -> None:
        if self.engine is None:
            raise ValueError("pg_trgm требует подключения к базе (engine)")
        self.position = {int(fid): i for i, fid in enumerate(self.faq["faq_id"])}

    def memory_mb(self) -> float:
        """Данные хранятся в PostgreSQL: размер таблицы faq вместе с индексами, МБ."""
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT pg_total_relation_size('faq')")).scalar() / 2 ** 20

    def scores(self, query: str) -> np.ndarray:
        with self.engine.connect() as conn:
            rows = conn.execute(SCORES_SQL, {"q": query}).all()
        s = np.zeros(len(self.faq))
        for faq_id, score in rows:
            if faq_id in self.position:
                s[self.position[faq_id]] = score
        return s
