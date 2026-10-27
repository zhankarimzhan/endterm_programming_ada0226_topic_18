"""Предобработка текста: нормализация, токенизация, стоп-слова, стемминг и лемматизация."""
import os
import re
from functools import lru_cache
from pathlib import Path

import nltk
from nltk.stem.snowball import SnowballStemmer

TOKEN_RE = re.compile(r"[a-zа-я0-9]+")

# Вопросительные слова есть в стандартном списке стоп-слов, но для FAQ они несут смысл вопроса
QUESTION_WORDS = {"как", "где", "когда", "сколько", "что", "какой", "какие", "какая", "каком", "зачем", "почему", "можно", "нужно"}

_stemmer = SnowballStemmer("russian")
_morph = None


def normalize(text: str) -> str:
    """Нижний регистр, ё → е."""
    return text.lower().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    """Разбивает текст на слова (кириллица, латиница, цифры)."""
    return TOKEN_RE.findall(normalize(text))


# Данные NLTK храним в папке проекта: NLTK не читает каталоги, доступные на запись другим пользователям
NLTK_DIR = Path(__file__).parent / "nltk_data"


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


@lru_cache(maxsize=None)
def stem(word: str) -> str:
    """Стемминг Snowball: отрезает окончание («поступления» → «поступлен»)."""
    return _stemmer.stem(word)


@lru_cache(maxsize=None)
def lemmatize(word: str) -> str:
    """Лемматизация pymorphy3: словарная форма («поступления» → «поступление»)."""
    global _morph
    if _morph is None:
        import pymorphy3
        _morph = pymorphy3.MorphAnalyzer()
    return _morph.parse(word)[0].normal_form


def preprocess(text: str, mode: str = "stem") -> list[str]:
    """Токены без стоп-слов; mode: 'none' — без нормализации слов, 'stem' — стемминг, 'lemma' — лемматизация."""
    tokens = [t for t in tokenize(text) if t not in STOPWORDS]
    if mode == "stem":
        return [stem(t) for t in tokens]
    if mode == "lemma":
        return [lemmatize(t) for t in tokens]
    return tokens


def preprocess_text(text: str, mode: str = "stem") -> str:
    """То же, что preprocess, но строкой (для векторизаторов scikit-learn)."""
    return " ".join(preprocess(text, mode))
