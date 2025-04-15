import logging
import random
import sqlite3
import os
from dotenv import load_dotenv
from telegram import Update, BotCommand, BotCommandScopeAllGroupChats
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Ensure logging is set to debug level for more detailed output
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Add a debug log to confirm the bot is running
logger.debug("Bot is running and ready to process messages.")

# Database setup
def setup_database():
    conn = sqlite3.connect('markov_data.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS markov_data (
                        chat_id INTEGER,
                        word1 TEXT,
                        word2 TEXT,
                        next_word TEXT,
                        PRIMARY KEY (chat_id, word1, word2, next_word))''')
    conn.commit()
    conn.close()

# Save message data to the database
def save_to_database(chat_id, word_pairs):
    conn = sqlite3.connect('markov_data.db')
    cursor = conn.cursor()
    for word1, word2, next_word in word_pairs:
        cursor.execute('''INSERT OR IGNORE INTO markov_data (chat_id, word1, word2, next_word)
                          VALUES (?, ?, ?, ?)''', (chat_id, word1, word2, next_word))
    conn.commit()
    conn.close()

# Generate a message using Markov chains
def generate_message(chat_id):
    conn = sqlite3.connect('markov_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT word1, word2, next_word FROM markov_data WHERE chat_id = ?', (chat_id,))
    data = cursor.fetchall()
    conn.close()

    if not data:
        return "I don't have enough data to generate a message yet!"

    markov_dict = {}
    for word1, word2, next_word in data:
        markov_dict.setdefault((word1, word2), []).append(next_word)

    start_pair = random.choice(list(markov_dict.keys()))
    message = [start_pair[0], start_pair[1]]

    while len(message) < 50:  # Limit message length
        pair = (message[-2], message[-1])
        if pair not in markov_dict:
            break
        next_word = random.choice(markov_dict[pair])
        message.append(next_word)

    return ' '.join(message)

# Command to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hello! I am a Markov Chain Bot. Add me to a group and I will learn from the messages!')

# Handle incoming messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text
    words = text.split()

    # Log every message received
    logger.info(f"Received message in chat {chat_id}: {text}")

    # Log when a message is ignored
    if not text:
        logger.debug(f"Ignored a non-text message in chat {chat_id}.")
        return

    if len(words) < 3:
        return

    word_pairs = [(words[i], words[i + 1], words[i + 2]) for i in range(len(words) - 2)]
    save_to_database(chat_id, word_pairs)

# Send a random message to the group
async def send_random_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    message = generate_message(chat_id)
    await context.bot.send_message(chat_id=chat_id, text=message)

# Add a job to send random messages
async def schedule_random_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if not context.job_queue:
        await update.message.reply_text("Job queue is not initialized. Please try again later.")
        return

    context.job_queue.run_repeating(send_random_message, interval=random.randint(3600, 7200), first=10, chat_id=chat_id)
    await update.message.reply_text('I will now send random messages to this group!')

# Add a command to request a new message
async def request_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    message = generate_message(chat_id)
    await update.message.reply_text(message)

# Add bot command descriptions
def set_bot_commands(application):
    commands = [
        BotCommand("start", "Start the bot and get a welcome message"),
        # BotCommand("schedule", "Schedule random messages in the group"),
        BotCommand("request", "Request a generated message from the bot")
    ]
    application.bot.set_my_commands(commands, scope=None)  # Default scope for all users

    # Add commands specifically for group chats
    group_scope = BotCommandScopeAllGroupChats()
    application.bot.set_my_commands(commands, scope=group_scope)

# Main function to run the bot
def main():
    setup_database()
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    set_bot_commands(application)

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('schedule', schedule_random_messages))
    application.add_handler(CommandHandler('request', request_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Log when the bot starts polling
    logger.info("Bot has started polling for updates.")
    application.run_polling()
    logger.info("Bot has stopped polling.")

if __name__ == '__main__':
    main()