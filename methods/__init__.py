"""Методы поиска похожего вопроса: по файлу на метод, в каждом — алгоритм по шагам.
Порядок — от простого к сложному: rule_based → bow → tfidf → embeddings → pg_trgm (SQL)."""
from methods.base import SimilarityMethod
from methods.bow import BowMethod
from methods.embeddings import EmbeddingsMethod
from methods.pg_trgm import PgTrgmMethod
from methods.rule_based import RuleBasedMethod
from methods.tfidf import TfidfMethod

METHOD_CLASSES = {cls.name: cls for cls in (RuleBasedMethod, BowMethod, TfidfMethod, EmbeddingsMethod, PgTrgmMethod)}

__all__ = ["SimilarityMethod", "METHOD_CLASSES"]
