from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.session import (
    create_public_session,
    get_session,
    purge_expired_public_sessions,
)
from app.db.database import SessionLocal
from app.db.models import ConversationSession, User
from app.tools.registry_tools import build_registry


async def test_public_session_is_created_without_credentials():
    async with SessionLocal() as db:
        session = await create_public_session(db, language="en")
        await db.commit()

        assert session.user_id.startswith("guest-")
        assert await get_session(db, session.id) is not None
        guest = await db.get(User, session.user_id)
        assert guest is not None
        assert guest.memory_consent is False


async def test_public_registry_exposes_only_booking_tools():
    anonymous = build_registry(authenticated=False)
    assert set(anonymous.names) == {"check_availability", "create_booking"}


async def test_authenticated_registry_adds_owner_tools():
    owner = build_registry(authenticated=True)
    assert {"check_availability", "create_booking", "save_preference"} <= set(owner.names)


async def test_stale_guest_sessions_are_purged():
    async with SessionLocal() as db:
        stale = await create_public_session(db)
        fresh = await create_public_session(db)
        await db.commit()

        stale.created_at = datetime.utcnow() - timedelta(
            hours=settings.PUBLIC_SESSION_TTL_HOURS + 1
        )
        await db.commit()

        removed = await purge_expired_public_sessions(db)
        assert removed == 1
        assert await get_session(db, stale.id) is None
        assert await get_session(db, fresh.id) is not None
        assert await db.scalar(
            select(func.count(ConversationSession.id))
        ) == 1


def test_public_llm_config_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_LLM_API_KEY", "")
    monkeypatch.setattr(settings, "OPEN_ROUTER_API_KEY", "or-key")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")

    config = settings.public_llm_config()

    assert config is not None
    assert config["provider"] == "openrouter"
    assert config["api_key"] == "or-key"


def test_public_llm_config_returns_none_without_keys(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_LLM_API_KEY", "")
    monkeypatch.setattr(settings, "OPEN_ROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")

    assert settings.public_llm_config() is None
