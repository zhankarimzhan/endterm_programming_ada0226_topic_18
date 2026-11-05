"""pg_trgm: сходство по триграммам символов, считается в PostgreSQL (дополнительный SQL-метод).

Алгоритм
  Подготовка (fit):
    1. Вопросы уже лежат в таблице faq — индекс в Python не строится,
       запоминаем только позицию каждого faq_id, чтобы разложить оценки по порядку.
  Поиск (scores), в PostgreSQL:
    1. Запрос и вопрос → нижний регистр.
    2. Каждое слово режется на триграммы — тройки символов: «общага» → «  о», « об», «общ», «бща», «ага», «га ».
    3. word_similarity: какая доля триграмм запроса нашлась в самом похожем фрагменте вопроса, от 0 до 1.
       Устойчив к опечаткам и окончаниям, но не понимает синонимов.
"""
import numpy as np
from sqlalchemy import text

from methods.base import SimilarityMethod

# Шаги 1–3 поиска — одним запросом
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
