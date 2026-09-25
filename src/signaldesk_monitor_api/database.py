from __future__ import annotations
from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

class Base(DeclarativeBase): pass

def create_session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(create_engine(url, pool_pre_ping=True), expire_on_commit=False)

def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    with factory() as session:
        yield session
