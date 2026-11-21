import json
from datetime import timedelta

from sqlalchemy import func, select

from app.core.timeutil import today_local
from app.db.database import SessionLocal
from app.db.models import Booking
from app.tools.booking import SLOT_TIMES
from app.tools.registry import MemoryIdempotencyStore, ToolContext
from app.tools.registry_tools import build_registry
from tests.conftest import make_session


def ctx_for(session) -> ToolContext:
    return ToolContext(
        session_id=session.id,
        user_id=session.user_id,
        store=MemoryIdempotencyStore(),
    )


async def booking_count() -> int:
    async with SessionLocal() as db:
        return int(await db.scalar(select(func.count(Booking.id))) or 0)


def booking_args(day, time="19:30", party=4, confirmed=False) -> str:
    return json.dumps(
        {"date": str(day), "time": time, "party_size": party, "confirmed": confirmed}
    )


async def test_availability_returns_free_slots():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)

    result = await registry.execute(
        "check_availability",
        json.dumps({"date": str(tomorrow), "party_size": 4}),
        ctx_for(session),
    )

    assert result["ok"] is True
    assert result["slots"] == SLOT_TIMES


async def test_availability_rejects_party_size_over_limit():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)

    result = await registry.execute(
        "check_availability",
        json.dumps({"date": str(tomorrow), "party_size": 50}),
        ctx_for(session),
    )

    assert result["ok"] is False
    assert result["error"] == "invalid_arguments"


async def test_availability_rejects_past_date():
    session = await make_session()
    registry = build_registry(authenticated=False)
    yesterday = today_local() - timedelta(days=1)

    result = await registry.execute(
        "check_availability",
        json.dumps({"date": str(yesterday), "party_size": 2}),
        ctx_for(session),
    )

    assert result == {"ok": False, "error": "date_in_past"}


async def test_unconfirmed_call_asks_for_confirmation_and_writes_nothing():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)

    result = await registry.execute(
        "create_booking", booking_args(tomorrow), ctx_for(session)
    )

    assert result["ok"] is False
    assert result["error"] == "confirmation_required"
    assert result["pending"]["time"] == "19:30"
    assert await booking_count() == 0


async def test_confirmed_without_pending_is_refused():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)

    result = await registry.execute(
        "create_booking", booking_args(tomorrow, confirmed=True), ctx_for(session)
    )

    assert result["ok"] is False
    assert result["error"] == "confirmation_required"
    assert await booking_count() == 0


async def test_confirmed_mismatch_is_refused():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)
    ctx = ctx_for(session)

    await registry.execute("create_booking", booking_args(tomorrow, party=4), ctx)
    result = await registry.execute(
        "create_booking", booking_args(tomorrow, party=6, confirmed=True), ctx
    )

    assert result["ok"] is False
    assert result["error"] == "confirmation_mismatch"
    assert await booking_count() == 0


async def test_confirmed_after_proposal_creates_one_booking():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)
    ctx = ctx_for(session)

    await registry.execute("create_booking", booking_args(tomorrow), ctx)
    result = await registry.execute(
        "create_booking", booking_args(tomorrow, confirmed=True), ctx
    )

    assert result["ok"] is True
    assert result["booking_id"].startswith("BK-")
    assert await booking_count() == 1


async def test_repeat_confirmed_call_is_idempotent():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)
    ctx = ctx_for(session)

    await registry.execute("create_booking", booking_args(tomorrow), ctx)
    first = await registry.execute(
        "create_booking", booking_args(tomorrow, confirmed=True), ctx
    )
    second = await registry.execute(
        "create_booking", booking_args(tomorrow, confirmed=True), ctx
    )

    assert first == second
    assert await booking_count() == 1


async def test_taken_slot_is_reported_for_another_session():
    first_session = await make_session(user_id="guest-a")
    second_session = await make_session(user_id="guest-b")
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)

    for session in (first_session, second_session):
        ctx = ctx_for(session)
        await registry.execute("create_booking", booking_args(tomorrow), ctx)
        if session is first_session:
            await registry.execute(
                "create_booking", booking_args(tomorrow, confirmed=True), ctx
            )

    second = await registry.execute(
        "create_booking", booking_args(tomorrow, confirmed=True), ctx_for(second_session)
    )

    assert second["ok"] is False
    assert second["error"] == "slot_taken"
    assert await booking_count() == 1


async def test_availability_hides_booked_slot():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)

    ctx = ctx_for(session)
    await registry.execute("create_booking", booking_args(tomorrow), ctx)
    await registry.execute("create_booking", booking_args(tomorrow, confirmed=True), ctx)

    result = await registry.execute(
        "check_availability",
        json.dumps({"date": str(tomorrow), "party_size": 4}),
        ctx_for(session),
    )
    assert "19:30" not in result["slots"]


async def test_invalid_time_format_is_rejected():
    session = await make_session()
    registry = build_registry(authenticated=False)
    tomorrow = today_local() + timedelta(days=1)

    result = await registry.execute(
        "create_booking",
        json.dumps({"date": str(tomorrow), "time": "7pm", "party_size": 2, "confirmed": True}),
        ctx_for(session),
    )
    assert result["error"] == "invalid_arguments"
