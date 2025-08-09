import logging
import random
import os
import string
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

import config as config
import database as database
import markov as markov
import crud as crud
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


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message.chat.type == 'private':
        return True
    admins = await context.bot.get_chat_administrators(update.message.chat_id)
    return update.message.from_user.id in [admin.user.id for admin in admins]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("H-hello... I'm a Markov Chain Bot. I guess you can add me to a group, or whatever. It's not like I want you to. Baka!")


def get_starting_word_from_message(db, words, chat_id, force_use_word=False):
    word_from_user_chance = crud.get_word_from_user_chance(db, chat_id)
    if not force_use_word and random.random() > word_from_user_chance:
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

    words = [word.strip(string.punctuation).lower()
             for word in text.split() if word.strip(string.punctuation)]
    logger.info(f"Received message in chat {chat_id}: {text}")

    db = SessionLocal()
    try:
        if len(words) >= 1:
            word_sequence = ["<START>"] + words + ["<END>"]
            word_pairs = [(word_sequence[i], word_sequence[i + 1], word_sequence[i + 2])
                          for i in range(len(word_sequence) - 2)]
            markov.save_to_database(db, chat_id, word_pairs)

        should_respond = False
        is_private_chat = update.message.chat.type == "private"
        bot_names = ["marky", "марки"]
        is_mention = any(keyword in text.lower() for keyword in bot_names)
        is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id

        if is_mention or is_reply:
            words = [word for word in words if word not in bot_names]

        random_reply_chance = crud.get_random_reply_chance(db, chat_id)
        if is_private_chat or is_mention or is_reply or (random.random() < random_reply_chance):
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


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    db = SessionLocal()
    try:
        settings = crud.get_group_settings(db, chat_id)
        if not settings:
            settings = crud.update_group_settings(db, chat_id, {})

        markov_order = settings.markov_order if settings.markov_order is not None else config.MARKOV_ORDER
        random_reply_chance = settings.random_reply_chance if settings.random_reply_chance is not None else config.RANDOM_REPLY_CHANCE
        word_from_user_chance = settings.word_from_user_chance if settings.word_from_user_chance is not None else config.WORD_FROM_USER_CHANCE

        message = "<b>Group Settings</b>\n"
        message += f"MARKOV_ORDER: {markov_order}\n"
        message += f"RANDOM_REPLY_CHANCE: {random_reply_chance}\n"
        message += f"WORD_FROM_USER_CHANCE: {word_from_user_chance}\n"
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    finally:
        db.close()


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can change settings.")
        return

    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /set <setting_name> <value>")
        return

    setting_name = context.args[0].upper()
    value = context.args[1]
    chat_id = update.message.chat_id

    db = SessionLocal()
    try:
        if setting_name == "MARKOV_ORDER":
            try:
                value = int(value)
                if value not in [1, 2]:
                    raise ValueError
                crud.update_group_settings(
                    db, chat_id, {"markov_order": value})
                await update.message.reply_text(f"MARKOV_ORDER set to {value}")
            except ValueError:
                await update.message.reply_text("MARKOV_ORDER must be 1 or 2.")
        elif setting_name == "RANDOM_REPLY_CHANCE":
            try:
                value = float(value)
                if not 0 <= value <= 1:
                    raise ValueError
                crud.update_group_settings(
                    db, chat_id, {"random_reply_chance": value})
                await update.message.reply_text(f"RANDOM_REPLY_CHANCE set to {value}")
            except ValueError:
                await update.message.reply_text("RANDOM_REPLY_CHANCE must be between 0 and 1.")
        elif setting_name == "WORD_FROM_USER_CHANCE":
            try:
                value = float(value)
                if not 0 <= value <= 1:
                    raise ValueError
                crud.update_group_settings(
                    db, chat_id, {"word_from_user_chance": value})
                await update.message.reply_text(f"WORD_FROM_USER_CHANCE set to {value}")
            except ValueError:
                await update.message.reply_text("WORD_FROM_USER_CHANCE must be between 0 and 1.")
        else:
            await update.message.reply_text(f"Unknown setting: {setting_name}")
    finally:
        db.close()


async def feed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("Please reply to a text file to feed it to me.")
        return

    document = update.message.reply_to_message.document
    if document.file_size > config.MAX_FILE_SIZE_KB * 1024:
        await update.message.reply_text(f"File is too large. Max size is {config.MAX_FILE_SIZE_KB}KB.")
        return

    file = await context.bot.get_file(document.file_id)
    file_content = (await file.download_as_bytearray()).decode('utf-8')

    lines = file_content.splitlines()

    if not lines:
        await update.message.reply_text("The file appears to be empty.")
        return

    chat_id = update.message.chat_id
    db = SessionLocal()
    total_words_learned = 0
    lines_processed = 0
    try:
        for line in lines:
            words = [word.strip(string.punctuation).lower()
                     for word in line.split() if word.strip(string.punctuation)]

            if len(words) >= 1:
                word_sequence = ["<START>"] + words + ["<END>"]
                word_pairs = [(word_sequence[i], word_sequence[i + 1], word_sequence[i + 2])
                              for i in range(len(word_sequence) - 2)]
                markov.save_to_database(db, chat_id, word_pairs)
                total_words_learned += len(words)
                lines_processed += 1
        
        await update.message.reply_text(f"Thanks for the meal! I've learned {total_words_learned} words from {lines_processed} lines.")
    finally:
        db.close()


async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Start the bot."),
        BotCommand("request", "Request a generated message."),
        BotCommand("settings", "View group settings."),
        BotCommand("set", "Set a group setting (admins only)."),
        BotCommand("feed", "Feed a text file to the bot.")
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
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("set", set_command))
    application.add_handler(CommandHandler("feed", feed_command))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))

    application.post_init = set_bot_commands

    logger.info("Bot has started polling for updates.")
    application.run_polling()
    logger.info("Bot has stopped polling.")


if __name__ == "__main__":
    main()
