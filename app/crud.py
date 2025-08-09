import logging
from sqlalchemy.orm import Session
from sqlalchemy import select
from models import GroupSettings, MarkovData
import config as config

logger = logging.getLogger(__name__)


def get_group_settings(db: Session, chat_id: int) -> GroupSettings:
    return db.query(GroupSettings).filter(GroupSettings.chat_id == chat_id).first()


def update_group_settings(db: Session, chat_id: int, settings: dict) -> GroupSettings:
    group_settings = get_group_settings(db, chat_id)
    if not group_settings:
        group_settings = GroupSettings(chat_id=chat_id)
        db.add(group_settings)

    for key, value in settings.items():
        setattr(group_settings, key, value)

    db.commit()
    db.refresh(group_settings)
    return group_settings


def get_markov_order(db: Session, chat_id: int) -> int:
    settings = get_group_settings(db, chat_id)
    if settings and settings.markov_order is not None:
        return settings.markov_order
    return config.MARKOV_ORDER


def get_random_reply_chance(db: Session, chat_id: int) -> float:
    settings = get_group_settings(db, chat_id)
    if settings and settings.random_reply_chance is not None:
        return settings.random_reply_chance
    return config.RANDOM_REPLY_CHANCE


def get_word_from_user_chance(db: Session, chat_id: int) -> float:
    settings = get_group_settings(db, chat_id)
    if settings and settings.word_from_user_chance is not None:
        return settings.word_from_user_chance
    return config.WORD_FROM_USER_CHANCE
