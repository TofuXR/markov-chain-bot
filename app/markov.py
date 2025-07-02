import random
import logging
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from models import MarkovData
import config as config

logger = logging.getLogger(__name__)


def save_to_database(db: Session, chat_id: int, word_pairs: list):
    if not word_pairs:
        return

    try:
        if db.bind.dialect.name == "postgresql":
            stmt = pg_insert(MarkovData).values([
                {"chat_id": chat_id, "word1": w1, "word2": w2, "next_word": nw}
                for w1, w2, nw in word_pairs
            ])
            update_stmt = stmt.on_conflict_do_update(
                index_elements=["chat_id", "word1", "word2", "next_word"],
                set_=dict(updated_at=func.now())
            )
            db.execute(update_stmt)
        else:
            for word1, word2, next_word in word_pairs:
                instance = db.query(MarkovData).filter_by(
                    chat_id=chat_id, word1=word1, word2=word2, next_word=next_word
                ).first()
                if instance:
                    instance.updated_at = func.now()
                else:
                    instance = MarkovData(
                        chat_id=chat_id, word1=word1, word2=word2, next_word=next_word
                    )
                    db.add(instance)
        db.commit()
    except Exception as e:
        logger.error(f"Database error during save: {e}")
        db.rollback()


def word_exists_in_db(db: Session, chat_id: int, word: str) -> bool:
    try:
        stmt = select(func.count()).select_from(MarkovData).where(
            MarkovData.chat_id == chat_id,
            or_(MarkovData.word1 == word, MarkovData.word2 == word)
        )
        count = db.execute(stmt).scalar_one()
        return count > 0
    except Exception as e:
        logger.error(f"Error checking word existence: {e}")
        return False


def get_random_word_from_db(db: Session, chat_id: int) -> str | None:
    try:
        stmt = select(MarkovData.word1).where(
            MarkovData.chat_id == chat_id,
            MarkovData.word1.notin_(["<START>", "<END>"])
        ).order_by(func.random()).limit(1)

        result = db.execute(stmt).scalar_one_or_none()
        return result
    except Exception as e:
        logger.error(f"Error getting random word: {e}")
        return None


def build_markov_model(db: Session, chat_id: int):
    stmt = select(MarkovData.word1, MarkovData.word2,
                  MarkovData.next_word).where(MarkovData.chat_id == chat_id)
    data = db.execute(stmt).fetchall()

    if not data:
        return None, None

    transitions = defaultdict(lambda: defaultdict(int))
    starting_states = []

    for word1, word2, next_word in data:
        if config.MARKOV_ORDER == 1:
            if word1 == "<START>":
                starting_states.append(word2)
            transitions[word1][word2] += 1
        else:
            if word1 == "<START>":
                starting_states.append((word1, word2))
            transitions[(word1, word2)][next_word] += 1

    return transitions, starting_states


def generate_message(db: Session, chat_id: int, max_length=30, starting_word: str | None = None) -> str:
    transitions, starting_states = build_markov_model(db, chat_id)

    if not starting_states:
        return "Hmph. I don't have enough data to say anything. Don't expect me to talk if you don't talk first, baka!"

    message = []
    current_state = None
    soft_length_limit = max_length * 0.5

    if config.MARKOV_ORDER == 1:
        if starting_word and starting_word in transitions:
            current_state = starting_word
        else:
            current_state = random.choice(
                starting_states) if starting_states else None
        if current_state:
            message = [current_state]
    else:
        if starting_word:
            valid_states = [
                s for s in starting_states if s[1] == starting_word]
            if valid_states:
                current_state = random.choice(valid_states)
                message = [current_state[1]]
        if not current_state:
            current_state = random.choice(starting_states)
            message = [current_state[1]]

    while current_state and len(message) < max_length * 1.5:
        if current_state not in transitions:
            break

        next_words_map = transitions[current_state]
        words, counts = zip(*next_words_map.items())

        if len(message) > soft_length_limit and "<END>" in next_words_map:
            new_counts = list(counts)
            end_index = words.index("<END>")

            length_penalty = (len(message) - soft_length_limit) / \
                (max_length - soft_length_limit)
            boost_factor = 1 + 4 * length_penalty
            new_counts[end_index] = int(new_counts[end_index] * boost_factor)

            if len(message) > max_length:
                next_word = "<END>"
            else:
                next_word = random.choices(
                    words, weights=new_counts, k=1)[0]
        else:
            next_word = random.choices(words, weights=counts, k=1)[0]

        if next_word == "<END>":
            break

        message.append(next_word)

        if config.MARKOV_ORDER == 1:
            current_state = next_word
        else:
            current_state = (current_state[1], next_word)

    if not message:
        return "I tried, but I couldn't think of anything to say... It's not like I wanted to talk to you anyway!"

    return " ".join(word for word in message if word not in ["<START>", "<END>"])
