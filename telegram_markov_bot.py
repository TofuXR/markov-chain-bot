import logging
import random
import sqlite3
import os
import time
from datetime import datetime
import pytz
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict
import string

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Set timezone to Tokyo
TIMEZONE = pytz.timezone('Asia/Tokyo')

# Update logging level based on environment variable
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    datefmt='%Y-%m-%d %H:%M:%S %Z'
)
logging.Formatter.converter = lambda *args: datetime.now(TIMEZONE).timetuple()
logger = logging.getLogger(__name__)

# Add a debug log to confirm the bot is running
logger.debug("Bot is running and ready to process messages.")

# Add a new environment variable to control Markov order
MARKOV_ORDER = int(os.getenv('MARKOV_ORDER', 2))

# Configuration for random replies and inactivity detection
RANDOM_REPLY_CHANCE = float(os.getenv('RANDOM_REPLY_CHANCE', '0.01'))  # 1% chance to reply randomly
INACTIVITY_CHECK_INTERVAL = int(os.getenv('INACTIVITY_CHECK_INTERVAL', '3600'))  # Check every hour
INACTIVITY_THRESHOLD = int(os.getenv('INACTIVITY_THRESHOLD', '86400'))  # 24 hours of inactivity

# NEW: Control chance of using a word from user's message (for bot mentions and replies)
WORD_FROM_USER_CHANCE = float(os.getenv('WORD_FROM_USER_CHANCE', '0.6'))  # 60% chance to use user's word

# Store the last message timestamp for each chat
last_message_times = {}
last_bot_message_times = {}

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
        current_time = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
        for word1, word2, next_word in word_pairs:
            cursor.execute('''INSERT OR IGNORE INTO markov_data (chat_id, word1, word2, next_word, created_at, updated_at)
                              VALUES (?, ?, ?, ?, ?, ?)''', (chat_id, word1, word2, next_word, current_time, current_time))
            cursor.execute('''UPDATE markov_data SET updated_at = ?
                              WHERE chat_id = ? AND word1 = ? AND word2 = ? AND next_word = ?''', (current_time, chat_id, word1, word2, next_word))
        conn.commit()
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while saving: {e}")
    finally:
        conn.close()

# Check if a word exists in the database for a specific chat
def word_exists_in_db(chat_id, word):
    try:
        conn = sqlite3.connect('markov_data.db')
        cursor = conn.cursor()
        
        # Check if the word exists as word1 or word2
        cursor.execute('''

            SELECT COUNT(*) FROM markov_data 
            WHERE chat_id = ? AND (word1 = ? OR word2 = ?)
        ''', (chat_id, word, word))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"Error checking word existence: {e}")
        return False

# Get random words from the database for a specific chat
def get_random_word_from_db(chat_id):
    try:
        conn = sqlite3.connect('markov_data.db')
        cursor = conn.cursor()
        
        # Get a random word1 that's not a special token
        cursor.execute('''

            SELECT DISTINCT word1 FROM markov_data 
            WHERE chat_id = ? AND word1 NOT IN ('<START>', '<END>')
            ORDER BY RANDOM() LIMIT 1
        ''', (chat_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return result[0]
        return None
    except Exception as e:
        logger.error(f"Error getting random word: {e}")
        return None

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

# Enhanced message generation with optional starting word
def generate_message(chat_id, max_length=20, use_all_chats=False, starting_word=None):
    if use_all_chats:
        chat_id = None  # Use None to indicate all chats

    transitions, starting_states = build_markov_model(chat_id)

    if not starting_states:
        return "I don't have enough data to generate a message yet!"

    # Initialize message list that we'll build up
    message = []
    
    if MARKOV_ORDER == 1:
        if starting_word and starting_word in transitions:
            # Use the provided starting word if it exists in the model
            current_state = starting_word
            message = [current_state]
        else:
            # Fall back to random starting state, but exclude <START> token
            state = random.choice(starting_states)
            # Make sure we don't add <START> to the actual message
            if state != '<START>':
                current_state = state
                message = [current_state]
            else:
                # If we somehow get <START>, find another state
                for state_key in transitions.keys():
                    if state_key != '<START>' and state_key != '<END>':
                        current_state = state_key
                        message = [current_state]
                        break
    else:  # MARKOV_ORDER == 2
        if starting_word:
            # Find a valid starting state involving the starting word
            valid_states = [state for state in starting_states if state[1] == starting_word]
            if valid_states:
                current_state = random.choice(valid_states)
                # Only add the real word, not the <START> token
                message = [current_state[1]]
            else:
                # Find any state with starting_word as first element
                found = False
                for state in transitions.keys():
                    if isinstance(state, tuple) and state[0] != '<START>' and state[0] == starting_word:
                        current_state = state
                        message = [state[0], state[1]]  # Add both words
                        found = True
                        break
                
                if not found:
                    # Fall back to random starting state
                    current_state = random.choice(starting_states)
                    # Only add the second word, as the first is likely <START>
                    message = [current_state[1]]
        else:
            # Default behavior without starting word
            current_state = random.choice(starting_states)
            # Only add the second word, as the first is likely <START>
            message = [current_state[1]]

    # Generate the rest of the message
    if MARKOV_ORDER == 1:
        # Modify loop for Markov Order 1
        reached_end = False
        while not reached_end:
            # Skip if current state is not in transitions or is a special token
            if current_state not in transitions or current_state in ['<START>', '<END>']:
                break
                
            next_words = transitions[current_state]
            if not next_words:
                break

            words, counts = zip(*next_words.items())
            total = sum(counts)
            probabilities = [count / total for count in counts]
            
            # Force ending if at max length
            if len(message) >= max_length and '<END>' in words:
                next_word = '<END>'
            else:
                next_word = random.choices(words, weights=probabilities, k=1)[0]

            if next_word == '<END>':
                reached_end = True
                break
                
            if next_word != '<START>':  # Make sure we don't add <START>
                message.append(next_word)
                
            current_state = next_word

    else:  # MARKOV_ORDER == 2
        # Modify loop for Markov Order 2
        reached_end = False
        while not reached_end:
            if current_state not in transitions:
                break
                
            next_words = transitions[current_state]
            if not next_words:
                break

            words, counts = zip(*next_words.items())
            total = sum(counts)
            probabilities = [count / total for count in counts]

            # Force ending if at max length
            if len(message) >= max_length and '<END>' in words:
                next_word = '<END>'
            else:
                next_word = random.choices(words, weights=probabilities, k=1)[0]

            if next_word == '<END>':
                reached_end = True
                break
                
            if next_word != '<START>':  # Make sure we don't add <START>
                message.append(next_word)
                
            current_state = (current_state[1], next_word)

    # Filter out any <START> tokens that might have slipped through
    message = [word for word in message if word != '<START>' and word != '<END>']
    
    if not message:
        # If somehow we ended up with an empty message, try again without a starting word
        if starting_word:
            return generate_message(chat_id, max_length, use_all_chats, None)
        return "I don't have enough data to generate a coherent message yet!"

    generated_message = ' '.join(message)
    logger.info(f"Generated message: {generated_message}")
    return generated_message

# Command to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hello! I am a Markov Chain Bot. Add me to a group and I will learn from the messages!')

# Helper function to try to get a valid starting word from user message
def get_starting_word_from_message(words, chat_id, force_use_word=False):
    # Check if we should use a word from the user's message (unless forced)
    if not force_use_word and random.random() > WORD_FROM_USER_CHANCE:
        return None
        
    filtered_words = [w for w in words if w and len(w) > 2]  # Filter short words
    
    if not filtered_words:
        return None
        
    # Shuffle words to select a random one
    random.shuffle(filtered_words)
    
    for word in filtered_words:
        if word_exists_in_db(chat_id, word):
            return word
            
    return None

# Enhanced message handler to respond to user messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text
    words = [word.strip(string.punctuation).lower() for word in text.split()]

    logger.info(f"Received message in chat {chat_id}: {text}")
    
    # Update the last message time for this chat
    last_message_times[chat_id] = time.time()

    # Save message data regardless of bot interaction
    if text and len(words) >= 2:
        words = ['<START>'] + words + ['<END>']
        word_pairs = [(words[i], words[i + 1], words[i + 2]) for i in range(len(words) - 2)]
        save_to_database(chat_id, word_pairs)

    # Check if the bot should respond
    should_respond = False
    is_private_chat = update.message.chat.type == 'private'
    is_mention = any(keyword in text.lower() for keyword in ['marky', 'марки'])
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    
    if is_private_chat:
        should_respond = True
        logger.info(f"Bot is in a one-on-one chat with {chat_id}")
    elif is_mention or is_reply:
        should_respond = True
        logger.info(f"Bot was {'mentioned' if is_mention else 'replied to'} in chat {chat_id}")
    elif random.random() < RANDOM_REPLY_CHANCE:
        should_respond = True
        logger.info(f"Randomly decided to reply in chat {chat_id}")

    if should_respond:
        # Try to get a starting word from the user's message
        # Force word usage for random replies, otherwise use probability
        force_use_word = not (is_mention or is_reply)
        valid_start_word = get_starting_word_from_message(words, chat_id, force_use_word=force_use_word)
        
        # Generate and send the message
        message = generate_message(chat_id, starting_word=valid_start_word)
        await update.message.reply_text(message)
        last_bot_message_times[chat_id] = time.time()

# Check for inactive chats and respond if needed
async def check_inactivity(context: ContextTypes.DEFAULT_TYPE):
    current_time = time.time()
    
    for chat_id, last_time in last_message_times.items():
        # Skip if we've recently sent a message to this chat
        if chat_id in last_bot_message_times and current_time - last_bot_message_times.get(chat_id, 0) < INACTIVITY_THRESHOLD / 2:
            continue
            
        # If chat has been inactive for longer than the threshold
        if current_time - last_time > INACTIVITY_THRESHOLD:
            logger.info(f"Detected inactivity in chat {chat_id}. Sending a message.")
            
            # Generate a random message for the inactive chat
            random_word = get_random_word_from_db(chat_id)
            message = generate_message(chat_id, starting_word=random_word)
            
            try:
                await context.bot.send_message(chat_id=chat_id, text=message)
                last_bot_message_times[chat_id] = current_time
                
                # Reset inactivity timer to avoid spamming
                last_message_times[chat_id] = current_time
            except Exception as e:
                logger.error(f"Failed to send inactivity message to chat {chat_id}: {e}")

# Simplified request_message command without admin features
async def request_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    message = generate_message(chat_id)
    await update.message.reply_text(message)

# Add bot command descriptions
def set_bot_commands(application):
    commands = [
        BotCommand("start", "Start the bot and get a welcome message"),
        BotCommand("request", "Request a generated message from the bot")
    ]
    application.bot.set_my_commands(commands, scope=None)  # Default scope for all users

# Main function to run the bot
def main():
    setup_database()
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # set_bot_commands(application)

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('request', request_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Add the job to check for inactivity
    job_queue = application.job_queue
    job_queue.run_repeating(check_inactivity, interval=INACTIVITY_CHECK_INTERVAL, first=INACTIVITY_CHECK_INTERVAL)

    # Log when the bot starts polling
    logger.info("Bot has started polling for updates.")
    application.run_polling()
    logger.info("Bot has stopped polling.")

if __name__ == '__main__':
    main()