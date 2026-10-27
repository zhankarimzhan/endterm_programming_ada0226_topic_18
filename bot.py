"""Telegram-бот: отвечает на вопросы абитуриентов, находя самый похожий вопрос в FAQ. Метод поиска выбирается командой /method."""
import asyncio
import logging
import os

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from database import check_connection, get_engine
from search import build_methods, log_question

DEFAULT_METHOD = "tfidf"
MAX_MESSAGE_LEN = 4000   # лимит Telegram — 4096 символов

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

START_TEXT = ("Привет! Я отвечаю на вопросы о поступлении в Astana IT University.\n"
              "Просто напишите вопрос, например: «Как поступить в AITU?» или «Какие предметы ЕНТ нужны?»\n\n"
              "/method — выбрать метод поиска ответа")


def current_method(context: ContextTypes.DEFAULT_TYPE):
    """Метод, выбранный пользователем (или метод по умолчанию)."""
    methods = context.bot_data["methods"]
    name = context.user_data.get("method", context.bot_data["default_method"])
    return methods.get(name) or methods[context.bot_data["default_method"]]


def format_answer(results: list[dict], method) -> str:
    """Найденный вопрос, ответ, похожие вопросы и использованный метод."""
    best = results[0]
    msg = f"❓ {best['question']}\n\n{best['answer']}"
    others = [r["question"] for r in results[1:] if r["score"] >= method.min_score]
    if others:
        msg += "\n\nПохожие вопросы:\n" + "\n".join(f"• {q}" for q in others)
    footer = f"\n\n— {method.title}, сходство {best['score']:.2f}"
    return msg[:MAX_MESSAGE_LEN - len(footer)] + footer


def methods_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Кнопки выбора метода; текущий отмечен галочкой."""
    selected = current_method(context).name
    buttons = [[InlineKeyboardButton(("✅ " if name == selected else "") + m.title, callback_data=f"method:{name}")]
               for name, m in context.bot_data["methods"].items()]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


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
    if best is None or best["score"] < method.min_score:
        await update.message.reply_text("Не нашёл подходящего ответа. Попробуйте сформулировать вопрос иначе "
                                        f"или выбрать другой метод: /method\n\n— {method.title}")
        await asyncio.to_thread(log_question, engine, query, method, None, best["score"] if best else None)
        return

    await update.message.reply_text(format_answer(results, method))
    await asyncio.to_thread(log_question, engine, query, method, best["faq_id"], best["score"])


async def set_commands(app: Application) -> None:
    """Меню команд бота в Telegram."""
    await app.bot.set_my_commands([BotCommand("start", "Как пользоваться ботом"),
                                   BotCommand("method", "Выбрать метод поиска")])


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

    app = Application.builder().token(token).post_init(set_commands).build()
    app.bot_data.update(engine=engine, methods=methods,
                        default_method=DEFAULT_METHOD if DEFAULT_METHOD in methods else next(iter(methods)))
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("method", choose_method))
    app.add_handler(CallbackQueryHandler(method_selected, pattern=r"^method:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))
    print("Бот запущен. Методы:", ", ".join(m.title for m in methods.values()), "| Остановить: Ctrl+C")
    app.run_polling()


if __name__ == "__main__":
    main()
