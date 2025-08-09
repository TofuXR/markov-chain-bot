from sqlalchemy import PrimaryKeyConstraint, func, Integer, String, DateTime, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime


class Base(DeclarativeBase):
    pass


class GroupSettings(Base):
    __tablename__ = "group_settings"

    chat_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False)
    markov_order: Mapped[int] = mapped_column(Integer, nullable=True)
    random_reply_chance: Mapped[float] = mapped_column(Float, nullable=True)
    word_from_user_chance: Mapped[float] = mapped_column(Float, nullable=True)

    def __repr__(self):
        return f"<GroupSettings(chat_id={self.chat_id})>"


class MarkovData(Base):
    __tablename__ = "markov_data"

    chat_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word1: Mapped[str] = mapped_column(String, primary_key=True)
    word2: Mapped[str] = mapped_column(String, primary_key=True)
    next_word: Mapped[str] = mapped_column(String, primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("chat_id", "word1", "word2",
                             "next_word", name="markov_data_pk"),
    )

    def __repr__(self):
        return f"<MarkovData(chat_id={self.chat_id}, words=({self.word1}, {self.word2}) -> {self.next_word})>"
