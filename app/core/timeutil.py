"""Business-timezone date helpers.

Relative dates ("tomorrow", "next Monday") must be resolved against the
restaurant's local calendar, not the server's UTC clock.
"""

from __future__ import annotations

from datetime import date, datetime
import pytz

from app.core.config import settings


def now_local() -> datetime:
    # pytz ships its own IANA timezone database, which works on Windows where
    # Python's zoneinfo may not have system timezone data installed.
    return datetime.now(pytz.timezone(settings.TIMEZONE))


def today_local() -> date:
    return now_local().date()


def prompt_datetime_line() -> str:
    now = now_local()
    return (
        f"Current date: {now.strftime('%A, %d %B %Y')}. "
        f"Current time: {now.strftime('%H:%M')} ({settings.TIMEZONE}). "
        "Resolve relative dates such as 'tomorrow' against this date."
    )
