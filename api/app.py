"""API статистики бота: те же данные, что в дашборде Streamlit, в виде JSON.
Страница web/dashboard.html открывается на / и читает эти эндпоинты.
Вопросы можно задавать через API: POST /api/ask — ответ всех методов, итоговый ответ и разбор текста;
POST /api/feedback — оценка ответа. Документация: /api/docs.
Доступ — ключ DASHBOARD_KEY из .env: параметр ?key=... или заголовок X-Dashboard-Key.
Запуск: uvicorn api.app:app --host 0.0.0.0 --port 8000"""
import datetime
import json
import os
import threading
from decimal import Decimal
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import DataError, IntegrityError

from analytics.queries_runner import load_queries, run_named
from analytics.stats import (get_chat_log, get_comparison, get_daily, get_evaluation, get_method_stats, get_suggestions,
                             get_top_matched, get_totals, mark_resolved)
from db import check_connection, get_engine
from methods import METHOD_CLASSES
from preprocessing.explain import explain
from search.ask import ask as ask_question
from search.history import save_feedback

DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web" / "dashboard.html"

app = FastAPI(title="AITU FAQ Bot — статистика", docs_url="/api/docs", openapi_url="/api/openapi.json")
engine = get_engine()

_methods = None
_methods_lock = threading.Lock()


def methods():
    """Методы поиска готовятся при первом вопросе (embeddings грузятся ~10 с)."""
    global _methods
    with _methods_lock:
        if _methods is None:
            from search import build_methods
            _methods = build_methods(engine)
    return _methods


def check_key(key: str | None = Query(None), x_dashboard_key: str | None = Header(None)) -> None:
    """Адрес может быть доступен из интернета (мини-приложение Telegram), поэтому API закрыт ключом."""
    expected = os.getenv("DASHBOARD_KEY")
    if expected and expected not in (key, x_dashboard_key):
        raise HTTPException(status_code=403, detail="Нет доступа: откройте дашборд из бота командой /app")


def _plain(value):
    """Значения из базы, которые json не знает: даты → ISO, Decimal и numpy → число, UUID → строка."""
    if isinstance(value, (pd.Timestamp, datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → список записей, NaN → None."""
    return df.astype(object).where(df.notna(), None).to_dict("records")


def as_json(data: pd.DataFrame | dict | list) -> Response:
    if isinstance(data, pd.DataFrame):
        data = records(data)
    return Response(json.dumps(data, ensure_ascii=False, default=_plain), media_type="application/json")


api = Depends(check_key)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_PATH)


@app.get("/api/health")
def health() -> dict:
    return {"database": check_connection(engine)}


@app.get("/api/totals", dependencies=[api])
def totals() -> Response:
    """Всего вопросов, найдено / не найдено, 👍 / 👎."""
    return as_json(get_totals(engine))


@app.get("/api/methods", dependencies=[api])
def method_stats() -> Response:
    """По методам: доля найденных, сходство, отзывы, время, память, место."""
    return as_json(get_method_stats(engine))


@app.get("/api/evaluation", dependencies=[api])
def evaluation() -> Response:
    """Последний прогон на тестовых вопросах: P@1, P@3, MRR."""
    return as_json(get_evaluation(engine))


@app.get("/api/daily", dependencies=[api])
def daily() -> Response:
    """Вопросы по дням и режимам."""
    return as_json(get_daily(engine))


@app.get("/api/requests", dependencies=[api])
def requests_log(limit: int = Query(2000, ge=1, le=20000)) -> Response:
    """Ответ каждого метода на каждый запрос, новые сверху."""
    return as_json(get_chat_log(engine).head(limit))


@app.get("/api/comparison", dependencies=[api])
def comparison() -> Response:
    """Режим сравнения: ответы всех методов на запрос."""
    return as_json(get_comparison(engine))


@app.get("/api/top-matched", dependencies=[api])
def top_matched(limit: int = Query(10, ge=1, le=100)) -> Response:
    """Чаще всего выдаваемые ответы FAQ."""
    return as_json(get_top_matched(engine, limit))


@app.get("/api/suggestions", dependencies=[api])
def suggestions() -> Response:
    """Вопросы без подходящего ответа — кандидаты для пополнения FAQ."""
    return as_json(get_suggestions(engine))


class ResolveBody(BaseModel):
    ids: list[str]


@app.post("/api/suggestions/resolve", dependencies=[api])
def resolve(body: ResolveBody) -> dict:
    """Отмечает вопросы как обработанные (ответ добавлен в FAQ)."""
    mark_resolved(engine, body.ids)
    return {"resolved": len(body.ids)}


@app.get("/api/queries", dependencies=[api])
def queries() -> list[dict]:
    """Список аналитических запросов из queries.sql."""
    return [{"name": name, "title": q["title"]} for name, q in load_queries().items()]


@app.get("/api/queries/{name}", dependencies=[api])
def query(name: str) -> Response:
    """Результат запроса из queries.sql и его текст."""
    all_queries = load_queries()
    if name not in all_queries:
        raise HTTPException(status_code=404, detail=f"Нет запроса {name}")
    df = run_named(engine, name, all_queries)
    return as_json({"title": all_queries[name]["title"], "sql": all_queries[name]["sql"],
                    "columns": [str(c) for c in df.columns], "rows": [list(r.values()) for r in records(df)]})


class AskBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=500, description="вопрос пользователя")
    k: int = Field(3, ge=1, le=10, description="сколько кандидатов вернуть от каждого метода")
    methods: list[str] | None = Field(None, description=f"какие методы запустить (по умолчанию все): {', '.join(METHOD_CLASSES)}")
    save: bool = Field(True, description="записать вопрос в статистику (режим сравнения)")


@app.post("/api/ask", dependencies=[api])
def ask(body: AskBody) -> Response:
    """Вопрос → ответы всех методов, итоговый ответ (за который больше методов) и разбор:
    шаги предобработки, сколько методов нашли ответ, насколько они согласны. С save=true вопрос
    попадает в статистику, а request_id можно передать в /api/feedback."""
    unknown = set(body.methods or []) - set(METHOD_CLASSES)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Неизвестные методы: {', '.join(sorted(unknown))}")
    return as_json(ask_question(engine, methods(), body.text.strip(), body.k, body.methods, body.save))


@app.get("/api/analyze", dependencies=[api])
def analyze(text: str = Query(..., min_length=1, max_length=500)) -> dict:
    """Только разбор текста по шагам предобработки, без поиска."""
    return explain(text)


class FeedbackBody(BaseModel):
    request_id: str
    faq_id: int
    helpful: bool


@app.post("/api/feedback", dependencies=[api])
def feedback(body: FeedbackBody) -> dict:
    """👍 / 👎 на ответ faq_id для запроса из /api/ask (как кнопки в боте)."""
    try:
        save_feedback(engine, body.request_id, body.faq_id, body.helpful)
    except (IntegrityError, DataError):
        raise HTTPException(status_code=404, detail="Нет такого запроса или вопроса FAQ")
    return {"saved": True}
