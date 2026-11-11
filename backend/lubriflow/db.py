from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .config import settings

engine = create_engine(settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
Session = sessionmaker(engine, expire_on_commit=False)


def database():
    with Session() as session:
        yield session
