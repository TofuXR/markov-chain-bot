import pytz
import os


LOG_LEVEL = "INFO"
TIMEZONE = pytz.timezone("Asia/Tokyo")
MARKOV_ORDER = 2
RANDOM_REPLY_CHANCE = 0.01
WORD_FROM_USER_CHANCE = 0.6
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./markov_data.db")
MARKOV_ORDER = 2

# Random reply chance (between 0 and 1, recommended: 0.05 for 5%)
RANDOM_REPLY_CHANCE = 0.01

# Control chance of using a word from user's message (for bot mentions and replies)
WORD_FROM_USER_CHANCE = 0.6
