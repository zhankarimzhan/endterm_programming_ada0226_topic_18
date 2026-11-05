"""Шаги 1–2: нормализация текста и разбиение на слова."""
import re

TOKEN_RE = re.compile(r"[a-zа-я0-9]+")


def normalize(text: str) -> str:
    """Шаг 1. Нижний регистр, ё → е."""
    return text.lower().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    """Шаг 2. Разбивает нормализованный текст на слова (кириллица, латиница, цифры)."""
    return TOKEN_RE.findall(normalize(text))
