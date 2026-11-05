"""Шаг 3: стоп-слова — частые служебные слова («в», «и», «на»), которые не помогают отличить один вопрос от другого."""
import os
from pathlib import Path

import nltk

# Вопросительные слова есть в стандартном списке стоп-слов, но для FAQ они несут смысл вопроса
QUESTION_WORDS = {"как", "где", "когда", "сколько", "что", "какой", "какие", "какая", "каком", "зачем", "почему", "можно", "нужно"}

# Данные NLTK храним в папке проекта: NLTK не читает каталоги, доступные на запись другим пользователям
NLTK_DIR = Path(__file__).resolve().parents[1] / "nltk_data"


def load_stopwords() -> set[str]:
    """Русские стоп-слова NLTK без вопросительных слов; при первом запуске скачивает список в папку проекта."""
    nltk.data.path.insert(0, str(NLTK_DIR))
    try:
        words = nltk.corpus.stopwords.words("russian")
    except LookupError:
        old_umask = os.umask(0o022)      # файлы только для владельца на запись
        try:
            NLTK_DIR.mkdir(mode=0o755, exist_ok=True)
            nltk.download("stopwords", download_dir=str(NLTK_DIR), quiet=True)
        finally:
            os.umask(old_umask)
        words = nltk.corpus.stopwords.words("russian")
    return set(words) - QUESTION_WORDS


STOPWORDS = load_stopwords()


def remove_stopwords(tokens: list[str]) -> list[str]:
    """Убирает стоп-слова из списка токенов."""
    return [t for t in tokens if t not in STOPWORDS]
