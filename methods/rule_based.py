"""Baseline (rule-based): правила замены синонимов + доля общих слов (коэффициент Жаккара)."""
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
    text = normalize(text)
    for pattern, repl in RULES.items():
        text = re.sub(pattern, repl, text)
    return text


class RuleBasedMethod(SimilarityMethod):
    name = "rule_based"
    title = "Rule-based (baseline)"
    preprocessing = "stem"
    min_score = 0.15

    def _fit(self, questions: list[str]) -> None:
        self.doc_sets = [set(preprocess(apply_rules(q), self.preprocessing)) for q in questions]

    def scores(self, query: str) -> np.ndarray:
        q = set(preprocess(apply_rules(query), self.preprocessing))
        if not q:
            return np.zeros(len(self.doc_sets))
        return np.array([len(q & d) / len(q | d) if d else 0.0 for d in self.doc_sets])
