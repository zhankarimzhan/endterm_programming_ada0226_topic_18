# ER-диаграмма базы данных

PostgreSQL 16, схема в третьей нормальной форме (`sql/init/01_schema.sql`). GitHub отображает диаграмму автоматически.

```mermaid
erDiagram
    categories ||--o{ faq : "категория"
    faq ||--o{ faq_terms : "содержит"
    terms ||--o{ faq_terms : "встречается в"
    requests ||--o{ method_runs : "обработан методами"
    methods ||--o{ method_runs : "запущен"
    method_runs ||--o{ candidates : "топ-k ответов"
    faq ||--o{ candidates : "найден как"
    requests ||--o{ feedback : "оценки"
    faq ||--o{ feedback : "оценён"
    requests ||--o| resolutions : "обработан"
    faq ||--o{ test_queries : "правильный ответ"
    methods ||--o{ runs : "оценка метода"
    runs ||--o{ predictions : "ответы"
    test_queries ||--o{ predictions : "на вопрос"
    faq ||--o{ predictions : "найден"

    categories {
        int category_id PK
        text name UK
    }
    faq {
        int faq_id PK
        text question
        text answer
        text raw_label
        int category_id FK
    }
    terms {
        int term_id PK
        text term UK "стемм слова"
    }
    faq_terms {
        int faq_id PK,FK
        int term_id PK,FK
        smallint tf "частота в вопросе"
    }
    methods {
        int method_id PK
        text name
        text preprocessing
        text title
        real min_score "порог"
        real fit_seconds
        real memory_mb
        timestamp updated_at
    }
    requests {
        uuid request_id PK
        text query_text
        text mode "compare / single"
        timestamp asked_at
    }
    method_runs {
        uuid request_id PK,FK
        int method_id PK,FK
        real latency_ms
    }
    candidates {
        uuid request_id PK,FK
        int method_id PK,FK
        smallint rank PK
        int faq_id FK
        real score
    }
    feedback {
        uuid request_id PK,FK
        int faq_id PK,FK
        boolean helpful
        timestamp created_at
    }
    resolutions {
        uuid request_id PK,FK
        timestamp resolved_at
    }
    test_queries {
        int query_id PK
        text text
        int true_faq_id FK
    }
    runs {
        int run_id PK
        int method_id FK
        numeric p_at_1
        numeric p_at_3
        numeric mrr
        numeric time_ms
        numeric memory_mb
        timestamp created_at
    }
    predictions {
        int run_id PK,FK
        int query_id PK,FK
        smallint rank PK
        int faq_id FK
        real score
    }
```

## Логика схемы

| Блок | Таблицы | Зачем так |
|---|---|---|
| Корпус | `faq`, `categories` | вопросы и ответы датасета; категории — после сведения 422 исходных меток |
| Обратный индекс | `terms`, `faq_terms` | связь «многие-ко-многим» вопрос ↔ стемм; по ней SQL считает частоты, документную частоту, TF-IDF и находит почти-дубликаты |
| Методы | `methods` | порог `min_score`, время подготовки и память каждого метода |
| Работа бота | `requests` → `method_runs` → `candidates` | вопрос хранится один раз; запуск метода (время поиска) отдельно от его топ-k кандидатов — время относится к паре «запрос-метод», а не к каждому кандидату |
| Оценки | `feedback`, `resolutions` | пользователь оценивает **ответ** (запрос + faq_id), а не метод: засчитан ли метод, вычисляется — так одна оценка автоматически распределяется между всеми методами, вернувшими этот ответ |
| Оценка на тестах | `test_queries`, `runs`, `predictions` | Precision@k и MRR на размеченных вопросах |

Вычисляемые данные — **представления** (`sql/init/03_views.sql`), а не таблицы:

- `v_method_answers` — ответ каждого метода на каждый запрос: найден ли (оценка ≥ порога метода) и засчитан ли (по отзывам);
- `v_unanswered` — вопросы без подходящего ответа (`not_found` / `bad_answer`) с ближайшим кандидатом, кроме обработанных.

Аналитические запросы к схеме — `queries.sql` (12 запросов: JOIN, self-JOIN, GROUP BY / HAVING, подзапросы EXISTS / NOT EXISTS, CTE, LATERAL, оконные ROW_NUMBER / RANK / DENSE_RANK / SUM OVER / LAG).
