"""Test environment: isolated SQLite file, no Mongo, no network."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("MONGO_URL", "")
os.environ["DATABASE_URL"] = (
    f"sqlite+aiosqlite:///{Path(tempfile.mkdtemp(prefix='voice-test-')) / 'test.db'}"
)

import pytest_asyncio

from app.db.database import SessionLocal, engine
from app.db.models import Base, ConversationSession, User


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield


async def make_session(*, user_id: str = "guest-test", language: str | None = "en"):
    """Create a user + session directly, without going through HTTP."""
    async with SessionLocal() as db:
        db.add(User(id=user_id, email=None, memory_consent=False))
        session = ConversationSession(id=f"sess-{user_id}", user_id=user_id, language=language)
        db.add(session)
        await db.commit()
    return session
