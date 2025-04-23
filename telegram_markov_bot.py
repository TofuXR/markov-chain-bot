import logging
import random
import sqlite3
import os
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict
import string

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Update logging level based on environment variable
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)
logger = logging.getLogger(__name__)

# Add a debug log to confirm the bot is running
logger.debug("Bot is running and ready to process messages.")

# Add a new environment variable to control Markov order
MARKOV_ORDER = int(os.getenv('MARKOV_ORDER', 2))

# Load the bot owner's ID from environment variables
BOT_OWNER_ID = int(os.getenv('BOT_OWNER_ID', '0'))

# Database setup
def setup_database():
    conn = sqlite3.connect('markov_data.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS markov_data (
                        chat_id INTEGER,
                        word1 TEXT,
                        word2 TEXT,
                        next_word TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (chat_id, word1, word2, next_word))''')
    conn.commit()
    conn.close()

# Updated save_to_database function to handle database errors gracefully
def save_to_database(chat_id, word_pairs):
    try:
        conn = sqlite3.connect('markov_data.db')
        cursor = conn.cursor()
        for word1, word2, next_word in word_pairs:
            cursor.execute('''INSERT OR IGNORE INTO markov_data (chat_id, word1, word2, next_word, created_at, updated_at)
                              VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''', (chat_id, word1, word2, next_word))
            cursor.execute('''UPDATE markov_data SET updated_at = CURRENT_TIMESTAMP
                              WHERE chat_id = ? AND word1 = ? AND word2 = ? AND next_word = ?''', (chat_id, word1, word2, next_word))
        conn.commit()
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while saving: {e}")
    finally:
        conn.close()

# Updated function to build the Markov model to support 1st order
def build_markov_model(chat_id):
    conn = sqlite3.connect('markov_data.db')
    cursor = conn.cursor()
    if chat_id is None:
        cursor.execute('SELECT word1, word2, next_word FROM markov_data')
    else:
        cursor.execute('SELECT word1, word2, next_word FROM markov_data WHERE chat_id = ?', (chat_id,))
    data = cursor.fetchall()
    conn.close()

    if not data:
        return None, None

    transitions = defaultdict(lambda: defaultdict(int))
    starting_states = []

    for word1, word2, next_word in data:
        if MARKOV_ORDER == 1:
            # Treat word2 as the next word for 1st order
            if word1 == '<START>':
                starting_states.append(word2)
            transitions[word1][word2] += 1
        else:
            # Default 2nd order behavior
            if word1 == '<START>':
                starting_states.append((word1, word2))
            transitions[(word1, word2)][next_word] += 1

    return transitions, starting_states

# Updated function to generate a message to optionally use all chats' data
def generate_message(chat_id, max_length=20, use_all_chats=False):
    if use_all_chats:
        chat_id = None  # Use None to indicate all chats

    transitions, starting_states = build_markov_model(chat_id)

    if not starting_states:
        return "I don't have enough data to generate a message yet!"

    if MARKOV_ORDER == 1:
        current_state = random.choice(starting_states)
        message = [current_state]

        while len(message) < max_length:
            next_words = transitions[current_state]
            if not next_words:
                break

            words, counts = zip(*next_words.items())
            total = sum(counts)
            probabilities = [count / total for count in counts]
            next_word = random.choices(words, weights=probabilities, k=1)[0]

            if next_word == '<END>':
                break

            message.append(next_word)
            current_state = next_word
    else:
        current_state = random.choice(starting_states)
        message = [current_state[1]]

        while len(message) < max_length:
            next_words = transitions[current_state]
            if not next_words:
                break

            words, counts = zip(*next_words.items())
            total = sum(counts)
            probabilities = [count / total for count in counts]
            next_word = random.choices(words, weights=probabilities, k=1)[0]

            if next_word == '<END>':
                break

            message.append(next_word)
            current_state = (current_state[1], next_word)

    generated_message = ' '.join(message)
    logger.info(f"Generated message: {generated_message}")
    return generated_message

# Command to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hello! I am a Markov Chain Bot. Add me to a group and I will learn from the messages!')

# Updated message handler to respond to replies to the bot's messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text
    words = [word.strip(string.punctuation).lower() for word in text.split()]

    logger.info(f"Received message in chat {chat_id}: {text}")

    # Check if the bot is mentioned using substring matching
    if any(keyword in text.lower() for keyword in ['marky', 'марки']):
        logger.info(f"Bot was mentioned in chat {chat_id}. Generating a response.")
        message = generate_message(chat_id)
        await update.message.reply_text(message)

    # Save message data regardless of bot mention
    if text and len(words) >= 2:
        words = ['<START>'] + words + ['<END>']
        word_pairs = [(words[i], words[i + 1], words[i + 2]) for i in range(len(words) - 2)]
        save_to_database(chat_id, word_pairs)

    # Check if the message is a reply to the bot's message
    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        logger.info(f"Message is a reply to the bot in chat {chat_id}. Generating a response.")
        message = generate_message(chat_id)
        await update.message.reply_text(message)

# Send a random message to the group
async def send_random_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    message = generate_message(chat_id)
    await context.bot.send_message(chat_id=chat_id, text=message)

# Updated request_message command to restrict to the bot owner's DM
async def request_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    is_dm = update.message.chat.type == 'private'

    if not is_dm or update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("This command is restricted to the bot owner's DM chat.")
        return

    message = generate_message(chat_id, use_all_chats=True)
    await update.message.reply_text(message)

# Add bot command descriptions
def set_bot_commands(application):
    commands = [
        BotCommand("start", "Start the bot and get a welcome message"),
        BotCommand("request", "Request a generated message from the bot")
    ]
    application.bot.set_my_commands(commands, scope=None)  # Default scope for all users

    # Removed group chat-specific commands

# Main function to run the bot
def main():
    setup_database()
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # set_bot_commands(application)

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('request', request_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Log when the bot starts polling
    logger.info("Bot has started polling for updates.")
    application.run_polling()
    logger.info("Bot has stopped polling.")

if __name__ == '__main__':
    main()