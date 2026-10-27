"""Реестр методов поиска похожего вопроса."""
from methods.base import SimilarityMethod
from methods.bow import BowMethod
from methods.embeddings import EmbeddingsMethod
from methods.pg_trgm import PgTrgmMethod
from methods.rule_based import RuleBasedMethod
from methods.tfidf import TfidfMethod

METHOD_CLASSES = {cls.name: cls for cls in (RuleBasedMethod, BowMethod, TfidfMethod, EmbeddingsMethod, PgTrgmMethod)}

__all__ = ["SimilarityMethod", "METHOD_CLASSES"]
