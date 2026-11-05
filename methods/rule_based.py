"""Baseline (rule-based): правила замены синонимов + доля общих слов (коэффициент Жаккара).

Алгоритм
  Подготовка (fit), для каждого вопроса FAQ:
    1. Правила: разные написания и разговорные слова → один вид («аиту» → «aitu», «общага» → «общежитие»).
    2. Предобработка: токены → без стоп-слов → стеммы.
    3. Запоминаем множество слов вопроса.
  Поиск (scores):
    1–2. Те же правила и предобработка для запроса.
    3. Жаккар с каждым вопросом: |общие слова| / |все слова обоих|, от 0 до 1.
"""
import re

import numpy as np

from methods.base import SimilarityMethod
from preprocessing import normalize, preprocess

# Правила: разные написания и разговорные слова приводятся к одному виду
RULES = {
    r"\bаиту\b|\bastana it university\b|\bастана ит университет\w*": "aitu",
    r"\bобщаг\w*": "общежитие",
    r"\bуниверу?\b|\bвуз\w*": "университет",
    r"\bстипух\w*": "стипендия",
    r"\bцен\w*|\bоплат\w*|\bстоимост\w*": "стоимость",
    r"\bмагистр\w*": "магистратура",
}


def apply_rules(text: str) -> str:
    """Шаг 1. Замена синонимов по правилам RULES."""
    text = normalize(text)
    for pattern, repl in RULES.items():
        text = re.sub(pattern, repl, text)
    return text


def jaccard(a: set[str], b: set[str]) -> float:
    """Шаг 3. Доля общих слов: |a ∩ b| / |a ∪ b|."""
    return len(a & b) / len(a | b) if b else 0.0


class RuleBasedMethod(SimilarityMethod):
    name = "rule_based"
    title = "Rule-based (baseline)"
    preprocessing = "stem"
    min_score = 0.15

    def _words(self, text: str) -> set[str]:
        """Шаги 1–2: правила, затем предобработка; результат — множество слов."""
        return set(preprocess(apply_rules(text), self.preprocessing))

    def _fit(self, questions: list[str]) -> None:
        self.doc_sets = [self._words(q) for q in questions]

    def scores(self, query: str) -> np.ndarray:
        q = self._words(query)
        if not q:
            return np.zeros(len(self.doc_sets))
        return np.array([jaccard(q, d) for d in self.doc_sets])
