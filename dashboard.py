"""Дашборд Streamlit: статистика бота, запросы, ответы и совпадения, предложения для пополнения FAQ.
Открывается в браузере или как мини-приложение Telegram (команда /app в боте).
Запуск: streamlit run dashboard.py"""
import os

import pandas as pd
import plotly.express as px
import streamlit as st

from database import check_connection, get_engine
from stats import (get_chat_log, get_daily, get_method_stats, get_suggestions, get_top_matched, get_totals,
                   mark_resolved)

st.set_page_config(page_title="AITU FAQ Bot — статистика", page_icon="📊", layout="centered")


def check_access() -> bool:
    """Доступ по ключу из .env (DASHBOARD_KEY): адрес мини-приложения доступен из интернета."""
    key = os.getenv("DASHBOARD_KEY")
    return not key or st.query_params.get("key") == key


@st.cache_resource
def engine():
    return get_engine()


@st.cache_resource(show_spinner="Загрузка методов поиска…")
def methods():
    from search import build_methods
    return build_methods(engine())


@st.cache_data(ttl=30)
def load(name: str) -> pd.DataFrame | dict:
    loaders = {"totals": get_totals, "methods": get_method_stats, "log": get_chat_log,
               "daily": get_daily, "top": get_top_matched, "suggestions": get_suggestions}
    return loaders[name](engine())


def page_stats() -> None:
    t = load("totals")
    if not t["questions"]:
        st.info("Пока нет ни одного вопроса — напишите боту.")
        return
    rated = t["likes"] + t["dislikes"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Вопросов", t["questions"])
    c2.metric("Ответ найден", f"{round(100 * t['answered'] / t['questions'])}%")
    c3.metric("Довольны", f"{round(100 * t['likes'] / rated)}%" if rated else "—", help="доля 👍 среди оценённых ответов")
    c1, c2, c3 = st.columns(3)
    c1.metric("Не найдено", t["not_found"])
    c2.metric("👍", t["likes"])
    c3.metric("👎", t["dislikes"])

    st.subheader("По методам")
    m = load("methods")
    st.dataframe(m.rename(columns={"name": "метод", "questions": "вопросов", "answered": "найдено",
                                   "found_pct": "найдено, %", "avg_score": "ср. сходство", "likes": "👍",
                                   "dislikes": "👎", "satisfaction_pct": "довольны, %", "rank": "место"}),
                 hide_index=True, width="stretch")
    long = m.melt(id_vars="name", value_vars=["found_pct", "satisfaction_pct"], var_name="показатель", value_name="%")
    long["показатель"] = long["показатель"].map({"found_pct": "ответ найден", "satisfaction_pct": "довольны"})
    st.plotly_chart(px.bar(long, x="name", y="%", color="показатель", barmode="group",
                           labels={"name": "метод"}, range_y=[0, 100]), width="stretch")

    daily = load("daily")
    if not daily.empty:
        st.subheader("Вопросы по дням")
        st.plotly_chart(px.bar(daily, x="day", y="questions", color="method",
                               labels={"day": "день", "questions": "вопросов", "method": "метод"}),
                        width="stretch")


def page_queries() -> None:
    log = load("log")
    if log.empty:
        st.info("Пока нет вопросов.")
        return
    with st.expander("Фильтры", expanded=True):
        methods_sel = st.multiselect("Метод", sorted(log["method"].dropna().unique()))
        status = st.radio("Результат", ["все", "найден", "не найден"], horizontal=True)
        fb = st.radio("Отзыв", ["все", "👍", "👎", "без отзыва"], horizontal=True)
        text = st.text_input("Поиск по тексту вопроса")
    df = log
    if methods_sel:
        df = df[df["method"].isin(methods_sel)]
    if status != "все":
        df = df[df["found"] == (status == "найден")]
    if fb != "все":
        df = df[df["feedback"] == ("" if fb == "без отзыва" else fb)]
    if text:
        df = df[df["user_query"].str.contains(text, case=False, regex=False)]
    st.caption(f"Найдено записей: {len(df)}")
    st.dataframe(df[["asked_at", "user_query", "method", "matched_question", "score", "feedback"]]
                 .rename(columns={"asked_at": "время", "user_query": "вопрос", "method": "метод",
                                  "matched_question": "найденный вопрос FAQ", "score": "сходство", "feedback": "отзыв"}),
                 hide_index=True, width="stretch")
    with st.expander("Ответ на выбранный вопрос"):
        answered = df[df["found"]]
        if answered.empty:
            st.write("Нет найденных ответов по фильтру.")
        else:
            row = answered.iloc[st.selectbox("Вопрос", range(len(answered)),
                                             format_func=lambda i: answered.iloc[i]["user_query"])]
            st.markdown(f"**Найдено:** {row['matched_question']}  \n**Метод:** {row['method']}, сходство {row['score']}")
            st.write(row["matched_answer"])


def page_matches() -> None:
    log = load("log")
    if not log.empty and log["score"].notna().any():
        st.subheader("Распределение сходства по методам")
        st.caption("Сходство лучшего найденного вопроса; правее — увереннее совпадение")
        st.plotly_chart(px.box(log.dropna(subset=["score"]), x="method", y="score", points="all",
                               labels={"method": "метод", "score": "сходство"}), width="stretch")
    top = load("top")
    if not top.empty:
        st.subheader("Чаще всего выдаваемые ответы")
        st.dataframe(top.rename(columns={"question": "вопрос FAQ", "times": "раз", "avg_score": "ср. сходство"})
                     .drop(columns="faq_id"), hide_index=True, width="stretch")

    st.subheader("Проверить вопрос всеми методами")
    query = st.text_input("Вопрос", placeholder="например: сколько стоит обучение")
    if query:
        rows = []
        for m in methods().values():
            for rank, r in enumerate(m.search(query, 3), start=1):
                rows.append({"метод": m.title, "место": rank, "вопрос FAQ": r["question"],
                             "сходство": round(r["score"], 3), "проходит порог": "✓" if r["score"] >= m.min_score else ""})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def page_suggestions() -> None:
    st.caption("Вопросы, на которые бот не нашёл ответа или ответ не подошёл (👎) — кандидаты для пополнения FAQ")
    sug = load("suggestions")
    if sug.empty:
        st.success("Необработанных вопросов нет.")
        return
    st.dataframe(sug.drop(columns="ids").rename(columns={
        "question": "вопрос", "times": "раз", "reasons": "причина", "methods": "методы",
        "best_candidate": "что предложил бот", "best_score": "сходство", "last_asked": "последний раз"}),
        hide_index=True, width="stretch")
    done = st.multiselect("Отметить как обработанные (ответ добавлен в FAQ)", range(len(sug)),
                          format_func=lambda i: sug.iloc[i]["question"])
    if done and st.button("Отметить"):
        mark_resolved(engine(), [i for row in sug.iloc[done]["ids"] for i in row])
        st.cache_data.clear()
        st.rerun()


def main() -> None:
    if not check_access():
        st.error("Нет доступа. Откройте дашборд из бота командой /app.")
        st.stop()
    if not check_connection(engine()):
        st.error("Нет подключения к базе. Запустите: docker-compose up -d")
        st.stop()
    st.title("📊 AITU FAQ Bot")
    if st.button("🔄 Обновить"):
        st.cache_data.clear()
    tabs = st.tabs(["Статистика", "Запросы", "Совпадения", "Предложения"])
    for tab, page in zip(tabs, [page_stats, page_queries, page_matches, page_suggestions]):
        with tab:
            page()


main()
