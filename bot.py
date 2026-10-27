"""Telegram-бот: отвечает на вопросы абитуриентов, находя самый похожий вопрос в FAQ.
/method — выбор метода поиска, кнопки 👍/👎 — отзыв на ответ,
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
from search import build_methods, log_question, save_feedback, save_unanswered
from stats import format_stats

DEFAULT_METHOD = "tfidf"
MAX_MESSAGE_LEN = 4000   # лимит Telegram — 4096 символов
REMEMBER_ANSWERS = 20    # сколько последних ответов пользователя помнить для кнопки «не подошёл»

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

START_TEXT = ("Привет! Я отвечаю на вопросы о поступлении в Astana IT University.\n"
              "Просто напишите вопрос, например: «Как поступить в AITU?» или «Какие предметы ЕНТ нужны?»\n\n"
              "Под ответом можно отметить 👍 / 👎 — это помогает улучшать бота.\n"
              "/method — выбрать метод поиска ответа\n"
              "/stats — статистика\n"
              "/app — дашборд: запросы, ответы, совпадения, предложения")


def dashboard_url() -> str | None:
    """HTTPS-адрес дашборда (WEBAPP_URL) с ключом доступа (DASHBOARD_KEY)."""
    base = os.getenv("WEBAPP_URL", "").rstrip("/")
    if not base.startswith("https://"):
        return None
    key = os.getenv("DASHBOARD_KEY")
    return f"{base}/?{urlencode({'key': key})}" if key else base


def current_method(context: ContextTypes.DEFAULT_TYPE):
    """Метод, выбранный пользователем (или метод по умолчанию)."""
    methods = context.bot_data["methods"]
    name = context.user_data.get("method", context.bot_data["default_method"])
    return methods.get(name) or methods[context.bot_data["default_method"]]


def format_answer(question: str, answer_text: str, footer: str = "") -> str:
    msg = f"❓ {question}\n\n{answer_text}"
    return msg[:MAX_MESSAGE_LEN - len(footer)] + footer


def methods_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Кнопки выбора метода; текущий отмечен галочкой."""
    selected = current_method(context).name
    buttons = [[InlineKeyboardButton(("✅ " if name == selected else "") + m.title, callback_data=f"method:{name}")]
               for name, m in context.bot_data["methods"].items()]
    return InlineKeyboardMarkup(buttons)


def feedback_keyboard(log_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("👍 Подошёл", callback_data=f"fb:1:{log_id}"),
                                  InlineKeyboardButton("👎 Не подошёл", callback_data=f"fb:0:{log_id}")]])


def alternatives_keyboard(alternatives: list[dict]) -> InlineKeyboardMarkup:
    """Кнопки с другими похожими вопросами."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(r["question"][:60], callback_data=f"alt:{r['faq_id']}")]
                                 for r in alternatives])


def remember_answer(context: ContextTypes.DEFAULT_TYPE, log_id: int, method_name: str, results: list[dict]) -> None:
    """Запоминает варианты ответа, чтобы при 👎 предложить другие."""
    answers = context.user_data.setdefault("answers", {})
    answers[log_id] = {"method": method_name, "results": results}
    for old in list(answers)[:-REMEMBER_ANSWERS]:
        del answers[old]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)
    await set_menu_button(context, update.effective_chat.id)


async def choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Выберите метод поиска:", reply_markup=methods_keyboard(context))


async def method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    name = query.data.split(":", 1)[1]
    if name in context.bot_data["methods"]:
        context.user_data["method"] = name
    await query.answer(f"Метод: {current_method(context).title}")
    await query.edit_message_text(f"Метод поиска: {current_method(context).title}", reply_markup=methods_keyboard(context))


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    engine = context.bot_data["engine"]
    method = current_method(context)
    query = update.message.text.strip()
    try:
        results = await asyncio.to_thread(method.search, query, 3)
    except Exception:
        logging.exception("Ошибка поиска (%s)", method.name)
        await update.message.reply_text("Не удалось выполнить поиск, попробуйте позже или выберите другой метод: /method")
        return

    best = results[0] if results else None
    try:
        if best is None or best["score"] < method.min_score:
            # Ничего не найдено: сохраняем вопрос и лучшего (непрошедшего порог) кандидата
            log_id = await asyncio.to_thread(log_question, engine, query, method, None, best["score"] if best else None)
            if log_id:
                await asyncio.to_thread(save_unanswered, engine, log_id, "not_found", best["faq_id"] if best else None)
            await update.message.reply_text("Не нашёл подходящего ответа — вопрос сохранён, чтобы дополнить базу. "
                                            f"Попробуйте сформулировать иначе или выбрать другой метод: /method\n\n— {method.title}")
            return
        log_id = await asyncio.to_thread(log_question, engine, query, method, best["faq_id"], best["score"])
    except Exception:
        logging.exception("Не удалось записать вопрос в базу")
        log_id = None

    footer = f"\n\n— {method.title}, сходство {best['score']:.2f}"
    keyboard = None
    if log_id:
        remember_answer(context, log_id, method.name, results)
        keyboard = feedback_keyboard(log_id)
    await update.message.reply_text(format_answer(best["question"], best["answer"], footer), reply_markup=keyboard)


async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка 👍 / 👎 под ответом."""
    query = update.callback_query
    _, value, log_id = query.data.split(":")
    log_id, helpful = int(log_id), value == "1"
    engine = context.bot_data["engine"]
    try:
        await asyncio.to_thread(save_feedback, engine, log_id, helpful)
        if not helpful:
            await asyncio.to_thread(save_unanswered, engine, log_id, "bad_answer")
    except Exception:
        logging.exception("Не удалось сохранить отзыв")
        await query.answer("Не удалось сохранить отзыв, попробуйте позже")
        return

    await query.answer("Спасибо за отзыв!")
    await query.edit_message_reply_markup(reply_markup=None)   # убираем кнопки, чтобы не голосовать дважды
    if helpful:
        return

    info = context.user_data.get("answers", {}).get(log_id)
    method = context.bot_data["methods"].get(info["method"]) if info else None
    alternatives = [r for r in info["results"][1:] if r["score"] >= method.min_score] if method else []
    if alternatives:
        await query.message.reply_text("Вопрос сохранён. Возможно, вы имели в виду:",
                                       reply_markup=alternatives_keyboard(alternatives))
    else:
        await query.message.reply_text("Вопрос сохранён, чтобы дополнить базу ответов. "
                                       "Попробуйте сформулировать иначе или выбрать другой метод: /method")


async def alternative_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает ответ на выбранный альтернативный вопрос."""
    query = update.callback_query
    faq_id = int(query.data.split(":", 1)[1])
    item = context.bot_data["faq_index"].get(faq_id)
    await query.answer()
    if item is None:
        await query.message.reply_text("Этот вопрос больше не найден в базе.")
        return
    await query.message.reply_text(format_answer(*item))


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
    app.bot_data.update(engine=engine, methods=methods, faq_index=faq_index,
                        default_method=DEFAULT_METHOD if DEFAULT_METHOD in methods else next(iter(methods)))
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("method", choose_method))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("app", open_app))
    app.add_handler(CallbackQueryHandler(method_selected, pattern=r"^method:"))
    app.add_handler(CallbackQueryHandler(feedback, pattern=r"^fb:[01]:\d+$"))
    app.add_handler(CallbackQueryHandler(alternative_selected, pattern=r"^alt:\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))
    print("Бот запущен. Методы:", ", ".join(m.title for m in methods.values()), "| Остановить: Ctrl+C")
    app.run_polling()


if __name__ == "__main__":
    main()
