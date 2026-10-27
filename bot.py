"""Telegram-бот: отвечает на вопросы абитуриентов, находя самый похожий вопрос в FAQ (PostgreSQL)."""
import asyncio
import logging
import os

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from database import check_connection, get_engine
from search import log_question, search_faq

MIN_SCORE = 0.3          # ниже этого порога считаем, что подходящего вопроса нет
MAX_MESSAGE_LEN = 4000   # лимит Telegram — 4096 символов

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

START_TEXT = ("Привет! Я отвечаю на вопросы о поступлении в Astana IT University.\n"
              "Просто напишите вопрос, например: «Как поступить в AITU?» или «Какие предметы ЕНТ нужны?»")


def format_answer(results: list[dict]) -> str:
    """Собирает ответ: найденный вопрос, ответ и похожие вопросы."""
    best = results[0]
    msg = f"❓ {best['question']}\n\n{best['answer']}"
    others = [r["question"] for r in results[1:] if r["score"] >= MIN_SCORE]
    if others:
        msg += "\n\nПохожие вопросы:\n" + "\n".join(f"• {q}" for q in others)
    return msg[:MAX_MESSAGE_LEN]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    engine = context.bot_data["engine"]
    query = update.message.text.strip()
    try:
        results = await asyncio.to_thread(search_faq, engine, query, 3)
    except SQLAlchemyError:
        logging.exception("Ошибка поиска")
        await update.message.reply_text("База данных временно недоступна, попробуйте позже.")
        return

    if not results or results[0]["score"] < MIN_SCORE:
        await update.message.reply_text("Не нашёл подходящего ответа. Попробуйте сформулировать вопрос иначе.")
        await asyncio.to_thread(log_question, engine, query, None, results[0]["score"] if results else None)
        return

    await update.message.reply_text(format_answer(results))
    await asyncio.to_thread(log_question, engine, query, results[0]["faq_id"], results[0]["score"])


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Не задан TELEGRAM_BOT_TOKEN в .env (токен выдаёт @BotFather)")
        return
    engine = get_engine()
    if not check_connection(engine):
        return

    app = Application.builder().token(token).build()
    app.bot_data["engine"] = engine
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))
    print("Бот запущен. Остановить: Ctrl+C")
    app.run_polling()


if __name__ == "__main__":
    main()
