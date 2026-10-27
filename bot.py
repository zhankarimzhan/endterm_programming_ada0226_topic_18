"""Telegram-бот: отвечает на вопросы абитуриентов, находя самый похожий вопрос в FAQ.
По умолчанию — режим сравнения: на каждый вопрос ответы всех методов с оценкой сходства и временем поиска,
все результаты и отзывы сохраняются в статистику.
/method — выбор режима (сравнение или один метод), кнопки 👍/👎 — отзыв на ответ,
/stats — статистика, /app — дашборд в мини-приложении Telegram."""
import asyncio
import logging
import os
from urllib.parse import urlencode

from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update,
                      WebAppInfo)
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from database import check_connection, get_engine
from search import (build_methods, compare_all, log_comparison, log_single, save_feedback, timed_search,
                    unanswered_reason)
from stats import format_stats

COMPARE = "all"          # режим сравнения всех методов
DEFAULT_METHOD = COMPARE
COMPARE_TITLE = "🔀 Все методы (сравнение)"
MAX_MESSAGE_LEN = 4000   # лимит Telegram — 4096 символов
REMEMBER_ANSWERS = 20    # сколько последних ответов пользователя помнить для кнопок

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

START_TEXT = ("Привет! Я отвечаю на вопросы о поступлении в Astana IT University.\n"
              "Просто напишите вопрос, например: «Как поступить в AITU?» или «Какие предметы ЕНТ нужны?»\n\n"
              "По умолчанию я ищу ответ всеми методами сразу и показываю, что нашёл каждый. "
              "Откройте вариант ответа и отметьте 👍 / 👎 — так считается, какой метод лучше.\n\n"
              "/method — сравнение всех методов или один метод\n"
              "/stats — статистика\n"
              "/app — дашборд: запросы, ответы, совпадения, предложения")


def dashboard_url() -> str | None:
    """HTTPS-адрес дашборда (WEBAPP_URL) с ключом доступа (DASHBOARD_KEY)."""
    base = os.getenv("WEBAPP_URL", "").rstrip("/")
    if not base.startswith("https://"):
        return None
    key = os.getenv("DASHBOARD_KEY")
    return f"{base}/?{urlencode({'key': key})}" if key else base


def current_mode(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Выбор пользователя: COMPARE или имя метода."""
    name = context.user_data.get("method", DEFAULT_METHOD)
    return name if name == COMPARE or name in context.bot_data["methods"] else COMPARE


def current_method(context: ContextTypes.DEFAULT_TYPE):
    """Выбранный метод (None в режиме сравнения)."""
    mode = current_mode(context)
    return None if mode == COMPARE else context.bot_data["methods"][mode]


def mode_title(context: ContextTypes.DEFAULT_TYPE) -> str:
    method = current_method(context)
    return method.title if method else COMPARE_TITLE


def format_answer(question: str, answer_text: str, footer: str = "") -> str:
    msg = f"❓ {question}\n\n{answer_text}"
    return msg[:MAX_MESSAGE_LEN - len(footer)] + footer


def methods_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Кнопки выбора режима; текущий отмечен галочкой."""
    selected = current_mode(context)
    options = [(COMPARE, COMPARE_TITLE)] + [(name, m.title) for name, m in context.bot_data["methods"].items()]
    buttons = [[InlineKeyboardButton(("✅ " if name == selected else "") + title, callback_data=f"method:{name}")]
               for name, title in options]
    return InlineKeyboardMarkup(buttons)


def feedback_keyboard(faq_id: int, request_id: str) -> InlineKeyboardMarkup:
    """👍 / 👎 для ответа faq_id на запрос request_id."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("👍 Подошёл", callback_data=f"cfb:1:{faq_id}:{request_id}"),
                                  InlineKeyboardButton("👎 Не подошёл", callback_data=f"cfb:0:{faq_id}:{request_id}")]])


def candidates_keyboard(faq_ids: list[int], request_id: str, faq_index: dict, counts: dict[int, int] | None = None) -> InlineKeyboardMarkup:
    """Кнопки вариантов ответа: нажатие показывает ответ и кнопки оценки."""
    def label(i: int, fid: int) -> str:
        suffix = f" ({counts[fid]})" if counts else ""
        return f"{i}. {faq_index[fid][0][:45]}{suffix}"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label(i, fid), callback_data=f"cmp:{fid}:{request_id}")]
                                 for i, fid in enumerate(faq_ids, start=1)])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)
    await set_menu_button(context, update.effective_chat.id)


async def choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Выберите метод поиска:", reply_markup=methods_keyboard(context))


async def method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    name = query.data.split(":", 1)[1]
    if name == COMPARE or name in context.bot_data["methods"]:
        context.user_data["method"] = name
    await query.answer(f"Режим: {mode_title(context)}")
    await query.edit_message_text(f"Режим поиска: {mode_title(context)}", reply_markup=methods_keyboard(context))


def remember_request(context: ContextTypes.DEFAULT_TYPE, request_id: str, mode: str,
                     found_by: dict[int, list[str]], alternatives: list[int] | None = None) -> None:
    """Запоминает, какие методы нашли каждый ответ (для подписи при оценке) и запасные варианты (для 👎)."""
    requests = context.user_data.setdefault("requests", {})
    requests[request_id] = {"mode": mode, "found_by": found_by, "alternatives": alternatives or []}
    for old in list(requests)[:-REMEMBER_ANSWERS]:
        del requests[old]


def request_info(context: ContextTypes.DEFAULT_TYPE, request_id: str) -> dict:
    return context.user_data.get("requests", {}).get(request_id, {"mode": None, "found_by": {}, "alternatives": []})


def format_comparison(query: str, rows: list[dict]) -> str:
    """Сводка: что нашёл каждый метод, сходство и время поиска."""
    lines = [f"🔀 Сравнение методов: «{query}»", ""]
    for r in rows:
        m, best = r["method"], r["best"]
        score = f"{best['score']:.2f}" if best else "—"
        head = f"{'✅' if r['found'] else '❌'} {m.title} — {score} · {r['latency_ms']:.1f} мс"
        if r["found"]:
            lines += [head, f"      «{best['question'][:90]}»"]
        else:
            lines.append(head + " — не найдено (ниже порога)")
    return "\n".join(lines)[:MAX_MESSAGE_LEN]


async def compare_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    """Режим сравнения: ответы всех методов + кнопки с найденными вариантами."""
    engine = context.bot_data["engine"]
    rows = await asyncio.to_thread(compare_all, context.bot_data["methods"], query, 3)
    if not rows:
        await update.message.reply_text("Не удалось выполнить поиск, попробуйте позже.")
        return
    try:
        request_id = await asyncio.to_thread(log_comparison, engine, query, rows)
    except Exception:
        logging.exception("Не удалось записать сравнение в базу")
        request_id = None

    # Разные найденные ответы: какой ответ какими методами найден
    found_by: dict[int, list[str]] = {}
    best_score: dict[int, float] = {}
    for r in rows:
        if r["found"]:
            fid = r["best"]["faq_id"]
            found_by.setdefault(fid, []).append(r["method"].title)
            best_score[fid] = max(best_score.get(fid, 0), r["best"]["score"])
    text = format_comparison(query, rows)

    if not found_by:
        await update.message.reply_text(text + "\n\nНи один метод не нашёл ответа — вопрос сохранён, чтобы дополнить базу.")
        return
    order = sorted(found_by, key=lambda fid: (-len(found_by[fid]), -best_score[fid]))
    keyboard = None
    if request_id:
        remember_request(context, request_id, COMPARE, found_by)
        keyboard = candidates_keyboard(order, request_id, context.bot_data["faq_index"],
                                       {fid: len(found_by[fid]) for fid in order})
    await update.message.reply_text(text + "\n\nОткройте вариант ответа и отметьте, подошёл ли (в скобках — сколько методов его нашли):",
                                    reply_markup=keyboard)


async def show_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Полный ответ на выбранный вариант из сравнения + кнопки оценки."""
    query = update.callback_query
    _, fid, request_id = query.data.split(":", 2)
    fid = int(fid)
    await query.answer()
    item = context.bot_data["faq_index"].get(fid)
    if item is None:
        await query.message.reply_text("Этот вопрос больше не найден в базе.")
        return
    methods_found = request_info(context, request_id)["found_by"].get(fid, [])
    footer = f"\n\n— нашли: {', '.join(methods_found)}" if methods_found else ""
    await query.message.reply_text(format_answer(*item, footer=footer), reply_markup=feedback_keyboard(fid, request_id))


async def choice_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Оценка ответа (оба режима). Сохраняется в feedback; засчитывается методам, вернувшим этот ответ."""
    query = update.callback_query
    _, value, fid, request_id = query.data.split(":", 3)
    helpful, fid = value == "1", int(fid)
    engine = context.bot_data["engine"]
    try:
        await asyncio.to_thread(save_feedback, engine, request_id, fid, helpful)
        reason = None if helpful else await asyncio.to_thread(unanswered_reason, engine, request_id)
    except Exception:
        logging.exception("Не удалось сохранить отзыв")
        await query.answer("Не удалось сохранить отзыв, попробуйте позже")
        return
    await query.answer("Спасибо, сохранено в статистику!")
    await query.edit_message_reply_markup(reply_markup=None)   # убираем кнопки, чтобы не голосовать дважды

    info = request_info(context, request_id)
    if helpful:
        if info["mode"] == COMPARE:
            methods_found = info["found_by"].get(fid, [])
            await query.message.reply_text("👍 Засчитано методам: " + (", ".join(methods_found) or "нашедшим этот ответ")
                                           + ". Остальным методам — 👎.")
        return
    if info["alternatives"]:
        await query.message.reply_text("Возможно, вы имели в виду:",
                                       reply_markup=candidates_keyboard(info["alternatives"], request_id,
                                                                        context.bot_data["faq_index"]))
        info["alternatives"] = []   # предлагаем один раз
    elif reason:
        await query.message.reply_text("Ни один найденный ответ не подошёл — вопрос сохранён, чтобы дополнить базу.")
    else:
        await query.message.reply_text("👎 Сохранено. Посмотрите другие варианты в сообщении со сравнением выше.")


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    engine = context.bot_data["engine"]
    method = current_method(context)
    query = update.message.text.strip()
    if method is None:
        await compare_answer(update, context, query)
        return
    try:
        results, latency = await asyncio.to_thread(timed_search, method, query, 3)
    except Exception:
        logging.exception("Ошибка поиска (%s)", method.name)
        await update.message.reply_text("Не удалось выполнить поиск, попробуйте позже или выберите другой метод: /method")
        return

    # Запрос и все кандидаты метода сохраняются всегда; «не найдено» вычисляется в базе (порог метода)
    try:
        request_id = await asyncio.to_thread(log_single, engine, query, method, results, latency)
    except Exception:
        logging.exception("Не удалось записать вопрос в базу")
        request_id = None

    best = results[0] if results else None
    if best is None or best["score"] < method.min_score:
        await update.message.reply_text("Не нашёл подходящего ответа — вопрос сохранён, чтобы дополнить базу. "
                                        f"Попробуйте сформулировать иначе или выбрать другой метод: /method\n\n— {method.title}")
        return

    footer = f"\n\n— {method.title}, сходство {best['score']:.2f}, {latency:.1f} мс"
    keyboard = None
    if request_id:
        alternatives = [r["faq_id"] for r in results[1:] if r["score"] >= method.min_score]
        remember_request(context, request_id, method.name, {best["faq_id"]: [method.title]}, alternatives)
        keyboard = feedback_keyboard(best["faq_id"], request_id)
    await update.message.reply_text(format_answer(best["question"], best["answer"], footer), reply_markup=keyboard)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        report = await asyncio.to_thread(format_stats, context.bot_data["engine"])
    except Exception:
        logging.exception("Ошибка статистики")
        report = "Не удалось получить статистику, попробуйте позже."
    await update.message.reply_text(report[:MAX_MESSAGE_LEN])


async def set_menu_button(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Кнопка «Дашборд» рядом с полем ввода в чате пользователя (Telegram надёжно применяет её только для чата)."""
    url = dashboard_url()
    if url is None:
        return
    try:
        await context.bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonWebApp("Дашборд", WebAppInfo(url=url)))
    except TelegramError:
        logging.warning("Не удалось установить кнопку дашборда для чата %s", chat_id)


async def open_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка, открывающая дашборд как мини-приложение Telegram."""
    url = dashboard_url()
    if url is None:
        await update.message.reply_text("Дашборд не подключён: укажите HTTPS-адрес в WEBAPP_URL в .env "
                                        "(например, адрес туннеля cloudflared) и перезапустите бота.")
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Открыть дашборд", web_app=WebAppInfo(url=url))]])
    await update.message.reply_text("Статистика, запросы, совпадения и предложения:", reply_markup=keyboard)
    await set_menu_button(context, update.effective_chat.id)


async def set_commands(app: Application) -> None:
    """Меню команд бота и кнопка дашборда рядом с полем ввода (для всех пользователей)."""
    await app.bot.set_my_commands([BotCommand("start", "Как пользоваться ботом"),
                                   BotCommand("method", "Выбрать метод поиска"),
                                   BotCommand("stats", "Статистика ответов"),
                                   BotCommand("app", "Открыть дашборд")])
    url = dashboard_url()
    if url is None:
        return
    try:
        await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp("Дашборд", WebAppInfo(url=url)))
    except TelegramError:
        logging.warning("Не удалось установить кнопку дашборда в меню")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Не задан TELEGRAM_BOT_TOKEN в .env (токен выдаёт @BotFather)")
        return
    engine = get_engine()
    if not check_connection(engine):
        return
    methods = build_methods(engine)
    if not methods:
        print("Ни один метод поиска не удалось подготовить")
        return
    faq = next(iter(methods.values())).faq
    faq_index = {int(r.faq_id): (r.question, r.answer) for r in faq.itertuples()}

    app = Application.builder().token(token).post_init(set_commands).build()
    app.bot_data.update(engine=engine, methods=methods, faq_index=faq_index)
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("method", choose_method))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("app", open_app))
    app.add_handler(CallbackQueryHandler(method_selected, pattern=r"^method:"))
    app.add_handler(CallbackQueryHandler(show_candidate, pattern=r"^cmp:\d+:[0-9a-f-]{36}$"))
    app.add_handler(CallbackQueryHandler(choice_feedback, pattern=r"^cfb:[01]:\d+:[0-9a-f-]{36}$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))
    print("Бот запущен. Методы:", ", ".join(m.title for m in methods.values()), "| Остановить: Ctrl+C")
    app.run_polling()


if __name__ == "__main__":
    main()
