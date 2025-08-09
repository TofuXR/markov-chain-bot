import pytz
import os


LOG_LEVEL = "INFO"
TIMEZONE = pytz.timezone("Asia/Tokyo")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./markov_data.db")

# Markov Chain
MARKOV_ORDER = 2
RANDOM_REPLY_CHANCE = 0.01
WORD_FROM_USER_CHANCE = 0.6
MAX_FILE_SIZE_KB = 1024
MAX_JSON_FILE_SIZE_MB = 10
MAX_FILE_CHUNK_SIZE = 500
MAX_FILE_CHUNKS = 10
