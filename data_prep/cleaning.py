"""Шаг 2: базовая очистка FAQ."""
import pandas as pd


def normalize_text(s: pd.Series) -> pd.Series:
    """Убирает лишние пробелы и переносы строк."""
    return s.fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def is_header_row(df: pd.DataFrame) -> pd.Series:
    """Строки, повторяющие заголовок CSV («questions | answers | classes») внутри данных."""
    return (df["question"].str.lower() == "questions") & (df["answer"].str.lower() == "answers")


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Базовая очистка: пустые строки, точные дубликаты, повторяющиеся вопросы."""
    df = df.copy()
    # 2.1 лишние пробелы и переносы строк
    for col in ("question", "answer", "raw_label"):
        df[col] = normalize_text(df[col])
    # 2.2 пустые вопросы / ответы и копии заголовка CSV
    df = df[(df["question"] != "") & (df["answer"] != "")]
    df = df[~is_header_row(df)]
    # 2.3 точные дубликаты (вопрос + ответ)
    df = df.drop_duplicates(["question", "answer"])
    # 2.4 один вопрос с разными ответами: оставляем самый полный (длинный) ответ
    df = (df.assign(answer_len=df["answer"].str.len())
            .sort_values("answer_len", ascending=False)
            .drop_duplicates("question")
            .sort_index()
            .drop(columns="answer_len"))
    # 2.5 сквозная нумерация faq_id
    df = df.reset_index(drop=True)
    df.insert(0, "faq_id", df.index + 1)
    return df


def print_summary(raw: pd.DataFrame, clean_df: pd.DataFrame) -> None:
    """Короткая сводка: что было и что осталось после очистки."""
    q = normalize_text(raw["question"])
    a = normalize_text(raw["answer"])
    conflicts = pd.DataFrame({"q": q, "a": a}).groupby("q")["a"].nunique()
    print(f"Строк в исходных данных: {len(raw)}")
    print(f"Точных дубликатов (вопрос + ответ): {pd.DataFrame({'q': q, 'a': a}).duplicated().sum()}")
    print(f"Вопросов с разными ответами: {(conflicts > 1).sum()}")
    print(f"Строк без '?' (не похожи на вопрос): {(~q.str.contains(r'\?')).sum()}")
    print(f"Строк-копий заголовка CSV: {is_header_row(pd.DataFrame({'question': q, 'answer': a})).sum()}")
    print(f"Разных меток: {raw['raw_label'].nunique()}")
    print(f"Осталось после очистки: {len(clean_df)}")
