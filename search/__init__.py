"""Поиск ответа: подготовка методов, сравнение на одном запросе и запись истории в базу.

  runner.py   build_methods (обучение, время, память), timed_search, compare_all
  history.py  requests -> method_runs -> candidates; feedback (оценки)
  ask.py      вопрос → ответы всех методов, итоговый ответ и разбор (для API)
"""
from data_prep.storage import load_faq
from search.history import log_comparison, log_single, save_feedback, unanswered_reason
from search.runner import build_methods, compare_all, register_methods, timed_search

__all__ = ["load_faq", "build_methods", "register_methods", "timed_search", "compare_all",
           "log_comparison", "log_single", "save_feedback", "unanswered_reason"]
