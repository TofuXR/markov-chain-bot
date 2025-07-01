import logging
import random
import os
import string
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

import config as config
import database as database
import markov as markov
from database import SessionLocal

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s:%(name)s] %(message)s",
    level=config.LOG_LEVEL,
    datefmt="%Y-%m-%d %H:%M:%S"
)
logging.Formatter.converter = lambda *args: datetime.now(
    config.TIMEZONE).timetuple()
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("H-hello... I'm a Markov Chain Bot. I guess you can add me to a group, or whatever. It's not like I want you to. Baka!")


def get_starting_word_from_message(db, words, chat_id, force_use_word=False):
    if not force_use_word and random.random() > config.WORD_FROM_USER_CHANCE:
        return None

    filtered_words = [w for w in words if w and len(w) > 2]
    if not filtered_words:
        return None

    random.shuffle(filtered_words)

    for word in filtered_words:
        if markov.word_exists_in_db(db, chat_id, word):
            return word

    return None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text
    if not text:
        return

    words = [word.strip(string.punctuation).lower() for word in text.split()]
    logger.info(f"Received message in chat {chat_id}: {text}")

    db = SessionLocal()
    try:
        if len(words) >= 2:
            word_sequence = ["<START>"] + words + ["<END>"]
            word_pairs = [(word_sequence[i], word_sequence[i + 1], word_sequence[i + 2])
                          for i in range(len(word_sequence) - 2)]
            markov.save_to_database(db, chat_id, word_pairs)

        should_respond = False
        is_private_chat = update.message.chat.type == "private"
        is_mention = any(keyword in text.lower()
                         for keyword in ["marky", "марки"])
        is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id

        if is_private_chat or is_mention or is_reply or (random.random() < config.RANDOM_REPLY_CHANCE):
            should_respond = True
            if not (is_private_chat or is_mention or is_reply):
                logger.info(f"Randomly decided to reply in chat {chat_id}")

        if should_respond:
            force_use_word = not (is_mention or is_reply)
            valid_start_word = get_starting_word_from_message(
                db, words, chat_id, force_use_word=force_use_word)

            message = markov.generate_message(
                db, chat_id, starting_word=valid_start_word)
            await update.message.reply_text(message)
    finally:
        db.close()


async def request_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    db = SessionLocal()
    try:
        message = markov.generate_message(db, chat_id)
        await update.message.reply_text(message)
    finally:
        db.close()


async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Start the bot."),
        BotCommand("request", "Request a generated message.")
    ]
    await application.bot.set_my_commands(commands)


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical(
            "TELEGRAM_BOT_TOKEN environment variable not found! Exiting.")
        return

    logger.info("Setting up database...")
    database.setup_database()

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("request", request_message))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))

    application.post_init = set_bot_commands

    logger.info("Bot has started polling for updates.")
    application.run_polling()
    logger.info("Bot has stopped polling.")


if __name__ == "__main__":
    main()
