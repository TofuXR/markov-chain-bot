from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
import config as config

engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_database():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
    try:
        yield db
    finally:
        db.close()
