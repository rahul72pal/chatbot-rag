"""Async SQLAlchemy database lifecycle and request-scoped sessions."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import delete, select, text, event

from app.core.config import settings
from app.db.models import Base, ConversationSession, Message, ToolExecution, User, UserMemory


_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False, "timeout": 30.0} if _is_sqlite else {}

engine = create_async_engine(settings.DATABASE_URL, echo=False, connect_args=_connect_args)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    if _is_sqlite:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            try:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
            except Exception:
                pass
    async with engine.begin() as connection:
        if _is_sqlite:
            await connection.execute(text("PRAGMA busy_timeout=30000;"))
            await connection.execute(text("PRAGMA synchronous=NORMAL;"))
        await connection.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()


async def delete_voice_user(user_id: str) -> None:
    """Purge voice data when the authenticated MongoDB account is deleted."""
    async with SessionLocal.begin() as session:
        session_ids = select(ConversationSession.id).where(ConversationSession.user_id == user_id)
        await session.execute(delete(ToolExecution).where(ToolExecution.session_id.in_(session_ids)))
        await session.execute(delete(Message).where(Message.session_id.in_(session_ids)))
        await session.execute(delete(ConversationSession).where(ConversationSession.user_id == user_id))
        await session.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
        await session.execute(delete(User).where(User.id == user_id))


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
