import logging
import random
import sqlite3
import os
import time
from datetime import datetime
import pytz
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict
import string

# --- Environment & Configuration Loading ---
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logger_init = logging.getLogger(__name__) # Temporary logger for critical startup error
    logger_init.error("BOT_TOKEN environment variable not set. Exiting.")
    raise ValueError("BOT_TOKEN environment variable not set.")

TIMEZONE_STR = os.getenv('TELEGRAM_BOT_TIMEZONE', 'Asia/Tokyo') # Allow configuring timezone
TIMEZONE = pytz.timezone(TIMEZONE_STR)

LOG_LEVEL_STR = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

MARKOV_ORDER = int(os.getenv('MARKOV_ORDER', 2))
RANDOM_REPLY_CHANCE = float(os.getenv('RANDOM_REPLY_CHANCE', '0.01'))
INACTIVITY_CHECK_INTERVAL = int(os.getenv('INACTIVITY_CHECK_INTERVAL', '3600'))
INACTIVITY_THRESHOLD = int(os.getenv('INACTIVITY_THRESHOLD', '86400'))
WORD_FROM_USER_CHANCE = float(os.getenv('WORD_FROM_USER_CHANCE', '0.6')) # Chance to use user's word for mentions/replies

DATABASE_NAME = 'markov_data.db'
MAX_GENERATED_MESSAGE_LENGTH = int(os.getenv('MAX_GENERATED_MESSAGE_LENGTH', 20))


# --- Special Tokens ---
START_TOKEN = '<START>'
END_TOKEN = '<END>'

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=LOG_LEVEL,
    datefmt='%Y-%m-%d %H:%M:%S %Z'
)
logging.Formatter.converter = lambda *args: datetime.now(TIMEZONE).timetuple()
logger = logging.getLogger(__name__)

logger.debug("Bot configuration loaded and logger initialized.")
logger.info(f"Running with Markov Order: {MARKOV_ORDER}, Timezone: {TIMEZONE_STR}")

# --- Global State ---
# For simplicity, keeping these as global dictionaries.
# For larger applications, consider using context.bot_data or a dedicated state management class.
LAST_MESSAGE_TIMESTAMPS = defaultdict(float)  # chat_id -> timestamp
LAST_BOT_MESSAGE_TIMESTAMPS = defaultdict(float)  # chat_id -> timestamp


# --- Database Manager ---
class DatabaseManager:
    def __init__(self, db_name: str):
        self.db_name = db_name
        self._setup_database()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_name)

    def _setup_database(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''CREATE TABLE IF NOT EXISTS markov_data (
                                     chat_id INTEGER,
                                     word1 TEXT,
                                     word2 TEXT,
                                     next_word TEXT,
                                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                     PRIMARY KEY (chat_id, word1, word2, next_word))''')
                conn.commit()
            logger.info(f"Database '{self.db_name}' setup complete.")
        except sqlite3.Error as e:
            logger.error(f"SQLite error during database setup: {e}")
            raise

    def save_word_pairs(self, chat_id: int, word_pairs: list[tuple[str, str, str]]):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                current_time_str = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
                for word1, word2, next_word in word_pairs:
                    cursor.execute(f'''INSERT OR IGNORE INTO markov_data
                                         (chat_id, word1, word2, next_word, created_at, updated_at)
                                         VALUES (?, ?, ?, ?, ?, ?)''',
                                   (chat_id, word1, word2, next_word, current_time_str, current_time_str))
                    cursor.execute(f'''UPDATE markov_data SET updated_at = ?
                                         WHERE chat_id = ? AND word1 = ? AND word2 = ? AND next_word = ?''',
                                   (current_time_str, chat_id, word1, word2, next_word))
                conn.commit()
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error during save_word_pairs for chat_id {chat_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during save_word_pairs for chat_id {chat_id}: {e}")

    def word_exists(self, chat_id: int, word: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''SELECT COUNT(*) FROM markov_data
                                     WHERE chat_id = ? AND (word1 = ? OR word2 = ?)''',
                               (chat_id, word, word))
                count = cursor.fetchone()[0]
                return count > 0
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error checking word existence for chat_id {chat_id}, word '{word}': {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking word existence for chat_id {chat_id}, word '{word}': {e}")
            return False

    def get_random_db_word(self, chat_id: int) -> str | None:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''SELECT DISTINCT word1 FROM markov_data
                                     WHERE chat_id = ? AND word1 NOT IN (?, ?)
                                     ORDER BY RANDOM() LIMIT 1''',
                               (chat_id, START_TOKEN, END_TOKEN))
                result = cursor.fetchone()
                return result[0] if result else None
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error getting random word for chat_id {chat_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting random word for chat_id {chat_id}: {e}")
            return None

    def fetch_markov_data(self, chat_id: int | None = None) -> list[tuple[str, str, str]]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if chat_id is None: # For use_all_chats scenario
                    cursor.execute('SELECT word1, word2, next_word FROM markov_data')
                else:
                    cursor.execute('SELECT word1, word2, next_word FROM markov_data WHERE chat_id = ?', (chat_id,))
                return cursor.fetchall()
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error fetching markov data for chat_id {chat_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching markov data for chat_id {chat_id}: {e}")
            return []

# --- Markov Chain Generator ---
class MarkovChainGenerator:
    def __init__(self, db_manager: DatabaseManager, markov_order: int):
        self.db_manager = db_manager
        self.markov_order = markov_order
        self._is_fallback_call = False # Prevents recursion in generate

    def _build_model(self, chat_id: int | None) -> tuple[defaultdict | None, list | None]:
        data = self.db_manager.fetch_markov_data(chat_id)
        if not data:
            logger.debug(f"No data found in DB for chat_id {chat_id} to build model.")
            return None, None

        transitions = defaultdict(lambda: defaultdict(int))
        raw_starting_states = []

        for word1, word2, next_word_val in data:
            if self.markov_order == 1:
                if word1 == START_TOKEN:
                    raw_starting_states.append(word2)
                transitions[word1][word2] += 1
            else:  # MARKOV_ORDER == 2 (or default)
                state = (word1, word2)
                if word1 == START_TOKEN:
                    raw_starting_states.append(state)
                transitions[state][next_word_val] += 1
        
        # Filter starting states to ensure they are valid beginnings of a message
        starting_states = []
        if self.markov_order == 1:
            starting_states = [s for s in raw_starting_states if s not in [START_TOKEN, END_TOKEN]]
        else: # MARKOV_ORDER == 2
            starting_states = [s for s in raw_starting_states if s[1] not in [START_TOKEN, END_TOKEN]]

        if not transitions: logger.debug(f"Transitions model is empty for chat_id {chat_id}.")
        if not starting_states: logger.debug(f"No valid starting states found for chat_id {chat_id} after filtering.")
        
        return transitions, starting_states

    def _get_initial_state_and_message(self, transitions: defaultdict, starting_states: list, starting_word: str | None) -> tuple[any, list[str]]:
        message_parts = []
        current_state = None

        if not starting_states:
            return None, []

        if self.markov_order == 1:
            if starting_word and starting_word in transitions and starting_word not in [START_TOKEN, END_TOKEN]:
                current_state = starting_word
            else: # No valid starting_word provided or it's not in model, pick a random one
                valid_random_starts = [s for s in starting_states if s in transitions] #Ensure state exists as a key
                if valid_random_starts:
                    current_state = random.choice(valid_random_starts)
                else: # Fallback if filtered starting_states are not keys in transitions (edge case)
                    fallback_keys = [key for key in transitions.keys() if key not in [START_TOKEN, END_TOKEN]]
                    if fallback_keys: current_state = random.choice(fallback_keys)

            if current_state: message_parts = [current_state]

        else:  # MARKOV_ORDER == 2
            if starting_word:
                # Prefer states like (<START>, starting_word)
                possible_initial_states = [s for s in starting_states if s[1] == starting_word and s in transitions]
                if possible_initial_states:
                    current_state = random.choice(possible_initial_states)
                    message_parts = [current_state[1]]
                else:
                    # Fallback: (starting_word, some_other_word), not necessarily beginning of sentence
                    alternative_states = [
                        state_key for state_key in transitions.keys()
                        if isinstance(state_key, tuple) and state_key[0] == starting_word and state_key[0] != START_TOKEN
                    ]
                    if alternative_states:
                        current_state = random.choice(alternative_states)
                        message_parts = [current_state[0], current_state[1]]
            
            if not current_state: # Fallback to a random starting state if no starting_word or it yielded no state
                valid_random_starts = [s for s in starting_states if s in transitions]
                if valid_random_starts:
                    current_state = random.choice(valid_random_starts)
                    message_parts = [current_state[1]] # Add the actual first word

        return current_state, message_parts

    def _generate_next_word(self, transitions: defaultdict, current_state: any, current_message_len: int, max_len: int) -> str:
        if current_state not in transitions or not transitions[current_state]:
            return END_TOKEN

        next_word_options = transitions[current_state]
        words, counts = zip(*next_word_options.items())
        
        if current_message_len >= max_len and END_TOKEN in words:
            return END_TOKEN
        
        # Filter out START_TOKEN from potential next words
        valid_choices = []
        valid_counts = []
        for i, word in enumerate(words):
            if word != START_TOKEN:
                valid_choices.append(word)
                valid_counts.append(counts[i])

        if not valid_choices: # Only START_TOKEN was an option, or list became empty
            return END_TOKEN
        
        probabilities = [count / sum(valid_counts) for count in valid_counts]
        return random.choices(valid_choices, weights=probabilities, k=1)[0]

    def generate(self, chat_id: int, max_length: int = MAX_GENERATED_MESSAGE_LENGTH, use_all_chats: bool = False, starting_word: str | None = None) -> str:
        effective_chat_id = None if use_all_chats else chat_id
        transitions, starting_states = self._build_model(effective_chat_id)

        if not transitions or not starting_states:
            logger.warning(f"Not enough data to build model for chat_id: {effective_chat_id}. Transitions: {bool(transitions)}, Starts: {bool(starting_states)}")
            return "I don't have enough data to generate a message yet!"

        current_state, message_parts = self._get_initial_state_and_message(transitions, starting_states, starting_word)

        if not current_state or not message_parts:
            logger.warning(f"Could not determine a valid initial state for chat_id: {effective_chat_id} with starting_word: '{starting_word}'.")
            if starting_word and not self._is_fallback_call:
                try:
                    self._is_fallback_call = True
                    return self.generate(chat_id, max_length, use_all_chats, None) # Try without starting word
                finally:
                    self._is_fallback_call = False
            return "I'm having trouble starting a message right now!"
        
        # Main generation loop
        # Ensure message_parts is not empty before loop if current_state was found but message_parts remains empty (should not happen with current _get_initial_state_and_message)
        if not message_parts and current_state: 
            logger.error("Internal inconsistency: current_state set but message_parts empty.")
            return "An internal error occurred while starting the message."


        for _ in range(max_length - len(message_parts)): # Iterate up to max_length
            next_word = self._generate_next_word(transitions, current_state, len(message_parts), max_length)

            if next_word == END_TOKEN:
                break
            
            message_parts.append(next_word)

            if self.markov_order == 1:
                current_state = next_word
            else:  # MARKOV_ORDER == 2
                if not isinstance(current_state, tuple) or len(current_state) != 2:
                    logger.error(f"Invalid current_state for MARKOV_ORDER 2: {current_state}. Stopping generation.")
                    break # Avoid error
                current_state = (current_state[1], next_word)
        
        final_message_words = [word for word in message_parts if word not in [START_TOKEN, END_TOKEN]]

        if not final_message_words:
            logger.info(f"Generated empty message for chat_id {effective_chat_id}. Retrying without starting_word if applicable.")
            if starting_word and not self._is_fallback_call:
                try:
                    self._is_fallback_call = True
                    return self.generate(chat_id, max_length, use_all_chats, None)
                finally:
                    self._is_fallback_call = False
            return "I don't have enough data to generate a coherent message yet!"
        
        generated_text = ' '.join(final_message_words)
        logger.info(f"Generated message for chat_id {effective_chat_id} (len: {len(final_message_words)}): '{generated_text}'")
        return generated_text

# --- Helper Functions ---
def preprocess_text(text: str) -> list[str]:
    words = text.lower().split()
    processed_words = []
    for word in words:
        stripped_word = word.strip(string.punctuation)
        if stripped_word: # Avoid empty strings if word was only punctuation
            processed_words.append(stripped_word)
    return processed_words

def determine_starting_word(
    processed_text_words: list[str], 
    chat_id: int, 
    db_manager: DatabaseManager, 
    force_attempt_user_word: bool = False
) -> str | None:
    """
    Determines a starting word from the user's message.
    - If force_attempt_user_word is True: Always try to pick a word from user's message if possible.
    - If force_attempt_user_word is False: Use WORD_FROM_USER_CHANCE to decide whether to pick from user's message.
    """
    if not force_attempt_user_word and random.random() > WORD_FROM_USER_CHANCE:
        logger.debug("Skipping user word for starting_word based on WORD_FROM_USER_CHANCE.")
        return None
        
    eligible_words = [w for w in processed_text_words if len(w) > 2] # Filter short words
    if not eligible_words:
        logger.debug("No eligible words from user message to use as starting_word.")
        return None
        
    random.shuffle(eligible_words)
    for word in eligible_words:
        if db_manager.word_exists(chat_id, word):
            logger.debug(f"Using '{word}' from user message as starting_word.")
            return word
            
    logger.debug("No word from user message found in DB for starting_word.")
    return None

# --- Telegram Bot Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hello! I am a Markov Chain Bot. Add me to a group and I will learn from the messages!')

async def request_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'markov_generator' not in context.application.bot_data:
        logger.error("Markov generator not found in bot_data for /request command.")
        await update.message.reply_text("Sorry, I'm not properly initialized to do that right now.")
        return

    markov_gen: MarkovChainGenerator = context.application.bot_data['markov_generator']
    chat_id = update.message.chat_id
    message = markov_gen.generate(chat_id)
    await update.message.reply_text(message)

# --- Telegram Bot Message Handler ---
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return # Should be filtered by MessageHandler filters

    if 'db_manager' not in context.application.bot_data or \
       'markov_generator' not in context.application.bot_data:
        logger.error("db_manager or markov_generator not found in bot_data for handle_text_message.")
        return

    db_manager: DatabaseManager = context.application.bot_data['db_manager']
    markov_generator: MarkovChainGenerator = context.application.bot_data['markov_generator']

    chat_id = update.message.chat_id
    user_text = update.message.text
    
    logger.info(f"Received message in chat {chat_id} from user {update.message.from_user.id if update.message.from_user else 'Unknown'}: '{user_text}'")
    LAST_MESSAGE_TIMESTAMPS[chat_id] = time.time()

    processed_words = preprocess_text(user_text)

    # Save message data to database
    # Original logic: need at least two words from user to form sequences for the DB.
    if user_text and len(processed_words) >= 2:
        db_words_to_store = [START_TOKEN] + processed_words + [END_TOKEN]
        word_tuples_to_save = [
            (db_words_to_store[i], db_words_to_store[i+1], db_words_to_store[i+2])
            for i in range(len(db_words_to_store) - 2) # Ensures at least 3 elements for one tuple
        ]
        if word_tuples_to_save:
            db_manager.save_word_pairs(chat_id, word_tuples_to_save)
            logger.debug(f"Saved {len(word_tuples_to_save)} word pairs for chat_id {chat_id}.")
        else:
            logger.debug(f"Not enough words in '{user_text}' (processed: {processed_words}) to form word pairs for database.")
    else:
        logger.debug(f"Message '{user_text}' too short (processed: {processed_words}, len: {len(processed_words)}) to save to DB.")


    # Determine if bot should respond
    bot_is_mentioned = any(keyword in user_text.lower() for keyword in (context.bot.username.lower(), 'marky', 'марки'))
    is_reply_to_bot = update.message.reply_to_message and \
                      update.message.reply_to_message.from_user.id == context.bot.id
    is_private_chat = update.message.chat.type == 'private'

    should_respond = False
    response_reason = ""

    if is_private_chat:
        should_respond = True
        response_reason = "private chat"
    elif bot_is_mentioned:
        should_respond = True
        response_reason = "bot mention"
    elif is_reply_to_bot:
        should_respond = True
        response_reason = "reply to bot"
    elif random.random() < RANDOM_REPLY_CHANCE:
        should_respond = True
        response_reason = "random chance"

    if should_respond:
        logger.info(f"Bot decided to respond in chat {chat_id} due to: {response_reason}.")
        
        # For random replies, we *force an attempt* to use a user word if available.
        # For mentions/replies, we use WORD_FROM_USER_CHANCE.
        force_attempt_user_word_for_reply = (response_reason == "random chance")
        
        start_word = determine_starting_word(
            processed_words,
            chat_id,
            db_manager,
            force_attempt_user_word=force_attempt_user_word_for_reply
        )
        
        generated_message = markov_generator.generate(chat_id, starting_word=start_word)
        await update.message.reply_text(generated_message)
        LAST_BOT_MESSAGE_TIMESTAMPS[chat_id] = time.time()

# --- Background Job ---
async def check_inactivity_job(context: ContextTypes.DEFAULT_TYPE):
    if 'db_manager' not in context.application.bot_data or \
       'markov_generator' not in context.application.bot_data:
        logger.error("db_manager or markov_generator not found in bot_data for inactivity job.")
        return

    db_m: DatabaseManager = context.application.bot_data['db_manager']
    markov_gen: MarkovChainGenerator = context.application.bot_data['markov_generator']
    
    current_time = time.time()
    # Iterate over a copy of items in case the dict is modified (less likely for defaultdict(float) but good practice)
    for chat_id, last_msg_time in list(LAST_MESSAGE_TIMESTAMPS.items()):
        # Skip if bot recently sent a message to this chat (e.g. within half the inactivity threshold)
        if current_time - LAST_BOT_MESSAGE_TIMESTAMPS.get(chat_id, 0) < INACTIVITY_THRESHOLD / 2:
            continue

        if current_time - last_msg_time > INACTIVITY_THRESHOLD:
            logger.info(f"Chat {chat_id} is inactive (last user msg: {datetime.fromtimestamp(last_msg_time, TIMEZONE).strftime('%Y-%m-%d %H:%M:%S %Z')}). Generating message.")
            
            random_start_word = db_m.get_random_db_word(chat_id)
            message_to_send = markov_gen.generate(chat_id, starting_word=random_start_word)

            try:
                await context.bot.send_message(chat_id=chat_id, text=message_to_send)
                LAST_BOT_MESSAGE_TIMESTAMPS[chat_id] = current_time # Record bot's activity
                LAST_MESSAGE_TIMESTAMPS[chat_id] = current_time # Reset user inactivity timer for this chat
                logger.info(f"Sent inactivity message to chat {chat_id}.")
            except Exception as e: # Catch broad exceptions from PTB or network issues
                logger.error(f"Failed to send inactivity message to chat {chat_id}: {e}")
                # Consider removing chat_id from LAST_MESSAGE_TIMESTAMPS if bot is blocked,
                # or handle specific Telegram API errors (e.g., Forbidden).
                # For now, just log and continue.

# --- Bot Setup Function ---
async def post_init_setup(application: Application):
    """Set bot commands after application initialization."""
    commands = [
        BotCommand("start", "Start the bot and get a welcome message."),
        BotCommand("request", "Request a generated message from the bot.")
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands successfully set.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

# --- Main Function ---
def main():
    logger.info("Starting bot...")

    # Initialize core components
    try:
        db_manager = DatabaseManager(DATABASE_NAME)
    except Exception as e: # Catch critical DB setup errors
        logger.critical(f"Failed to initialize DatabaseManager: {e}. Bot cannot start.")
        return

    markov_generator = MarkovChainGenerator(db_manager, MARKOV_ORDER)

    # Build the application
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init_setup).build()

    # Store shared components in bot_data for access in handlers/jobs
    application.bot_data['db_manager'] = db_manager
    application.bot_data['markov_generator'] = markov_generator
    
    # Add handlers
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('request', request_message_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Add job queue for inactivity check
    if INACTIVITY_CHECK_INTERVAL > 0 and INACTIVITY_THRESHOLD > 0 :
        job_queue = application.job_queue
        job_queue.run_repeating(check_inactivity_job, interval=INACTIVITY_CHECK_INTERVAL, first=INACTIVITY_CHECK_INTERVAL)
        logger.info(f"Inactivity check job scheduled every {INACTIVITY_CHECK_INTERVAL}s for chats inactive over {INACTIVITY_THRESHOLD}s.")
    else:
        logger.info("Inactivity check job is disabled due to zero interval or threshold.")


    # Start polling
    logger.info("Bot has started polling for updates.")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Bot polling failed critically: {e}")
    finally:
        logger.info("Bot has stopped polling.")

if __name__ == '__main__':
    main()