"""Real booking tools. Business rules live here, not in the prompt."""

from __future__ import annotations

from datetime import datetime, timedelta
import datetime as dt
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.timeutil import today_local
from app.db.database import SessionLocal
from app.db.models import Booking, PendingConfirmation
from app.tools.registry import Tool, ToolContext

SLOT_TIMES = [
    "12:00", "12:30", "13:00", "13:30",
    "18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00",
]
PENDING_TTL_MINUTES = 15


class CheckAvailabilityArgs(BaseModel):
    date: dt.date = Field(description="Reservation date in YYYY-MM-DD format")
    party_size: int = Field(ge=1, le=12)


class CreateBookingArgs(BaseModel):
    date: dt.date = Field(description="Reservation date in YYYY-MM-DD format")
    time: str = Field(pattern=r"^[0-2][0-9]:[0-5][0-9]$")
    party_size: int = Field(ge=1, le=12)
    confirmed: bool = Field(
        description="True only after the user explicitly said yes to these exact details"
    )


async def _taken_slots(db, booking_date: date) -> set[str]:
    rows = await db.scalars(
        select(Booking.booking_time).where(
            Booking.booking_date == booking_date,
            Booking.status == "confirmed",
        )
    )
    return set(rows.all())


async def check_availability(args: CheckAvailabilityArgs, ctx: ToolContext) -> dict:
    if args.date < today_local():
        return {"ok": False, "error": "date_in_past"}

    async with SessionLocal() as db:
        taken = await _taken_slots(db, args.date)

    free = [slot for slot in SLOT_TIMES if slot not in taken]
    return {
        "ok": True,
        "date": str(args.date),
        "party_size": args.party_size,
        "slots": free,
    }


async def create_booking(args: CreateBookingArgs, ctx: ToolContext) -> dict:
    details = {
        "date": str(args.date),
        "time": args.time,
        "party_size": args.party_size,
    }

    # Gate 1: the model must ask first. An unconfirmed call only records the
    # proposal; it never writes a booking.
    if not args.confirmed:
        async with SessionLocal.begin() as db:
            pending = await db.scalar(
                select(PendingConfirmation).where(
                    PendingConfirmation.session_id == ctx.session_id
                )
            )
            if pending is None:
                db.add(
                    PendingConfirmation(
                        session_id=ctx.session_id,
                        tool="create_booking",
                        args=details,
                    )
                )
            else:
                pending.tool = "create_booking"
                pending.args = details
                pending.created_at = datetime.utcnow()
        return {
            "ok": False,
            "error": "confirmation_required",
            "pending": details,
            "message": (
                "Ask the user to confirm these exact details before booking. "
                f"Say: table for {args.party_size} on {args.date} at {args.time}."
            ),
        }

    # Gate 2: a confirmed call must match a fresh proposal from this session.
    async with SessionLocal.begin() as db:
        pending = await db.scalar(
            select(PendingConfirmation).where(
                PendingConfirmation.session_id == ctx.session_id
            )
        )
        if pending is None:
            return {
                "ok": False,
                "error": "confirmation_required",
                "message": (
                    "No pending confirmation for this session. Call create_booking "
                    "with confirmed=false and ask the user first."
                ),
            }
        stale = datetime.utcnow() - pending.created_at > timedelta(minutes=PENDING_TTL_MINUTES)
        if stale or pending.args != details:
            await db.delete(pending)
            return {
                "ok": False,
                "error": "confirmation_mismatch",
                "message": "Details changed or the confirmation expired. Ask again.",
            }

    if args.date < today_local():
        return {"ok": False, "error": "date_in_past"}
    if args.time not in SLOT_TIMES:
        return {"ok": False, "error": "invalid_time", "slots": SLOT_TIMES}

    async with SessionLocal() as db:
        taken = await _taken_slots(db, args.date)
        if args.time in taken:
            return {"ok": False, "error": "slot_taken", "date": str(args.date), "time": args.time}

        booking = Booking(
            reference=f"tmp-{uuid4().hex}",
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            booking_date=args.date,
            booking_time=args.time,
            party_size=args.party_size,
            status="confirmed",
        )
        db.add(booking)
        try:
            await db.flush()
            booking.reference = f"BK-{booking.id:04d}"
            await db.execute(
                delete(PendingConfirmation).where(
                    PendingConfirmation.session_id == ctx.session_id
                )
            )
            await db.commit()
        except IntegrityError:
            # Unique slot constraint: someone else took it between the check
            # and the insert, so no second row is ever written.
            await db.rollback()
            return {"ok": False, "error": "slot_taken", "date": str(args.date), "time": args.time}
        result = {
            "ok": True,
            "booking_id": booking.reference,
            "date": str(args.date),
            "time": args.time,
            "party_size": args.party_size,
        }
    return result


booking_tools = [
    Tool(
        "check_availability",
        "Check free reservation slots for a date and party size. Use before proposing a time.",
        CheckAvailabilityArgs,
        check_availability,
    ),
    Tool(
        "create_booking",
        (
            "Create a reservation. Call with confirmed=false first to obtain the details "
            "to read back, then only after the user says yes call with confirmed=true."
        ),
        CreateBookingArgs,
        create_booking,
        mutating=True,
    ),
]
