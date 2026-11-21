"""The agent loop: the model proposes tool calls, the backend executes them.

The loop is deliberately explicit instead of recursive: it is bounded by
``MAX_TOOL_ITERATIONS``, every tool result is persisted, and the model never
sees an unvalidated result. The final spoken text may only claim success when
a tool result said ``ok: true``.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.core.session import add_message, messages_for_llm
from app.core.timeutil import prompt_datetime_line
from app.tools.registry import ToolContext, ToolRegistry, tool_result_message

FALLBACK = "Sorry, I had trouble with that. Could you try again?"


def _system_prompt(base: str) -> str:
    return f"{base}\n\n{prompt_datetime_line()}"


def _text_of(content: Any) -> str:
    """Flatten string or content-block replies into plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        return " ".join(part for part in parts if part).strip()
    return ""


def _call_parts(call: dict[str, Any]) -> tuple[str, str | dict[str, Any], str]:
    fn = call.get("function") or {}
    name = str(fn.get("name") or "")
    args = fn.get("arguments")
    if args is None:
        args = "{}"
    call_id = str(call.get("id") or f"call_{name}")
    return name, args, call_id


async def run_turn(
    db: AsyncSession,
    session,
    user_text: str,
    llm,
    registry: ToolRegistry,
    ctx: ToolContext,
    *,
    memory_items: list[dict[str, str]] | None = None,
    system_prompt: str | None = None,
) -> str:
    """Run one user turn and return the text to speak."""
    await add_message(db, session_id=session.id, role="user", content=user_text)
    await db.commit()

    history = await messages_for_llm(db, session, memory_items=memory_items)
    # Release the read transaction: tool handlers open their own DB sessions,
    # and SQLite readers would otherwise block those writes.
    await db.commit()
    system_prompt = _system_prompt(system_prompt or history[0]["content"])
    working: list[dict[str, Any]] = list(history[1:])

    for iteration in range(max(1, settings.MAX_TOOL_ITERATIONS)):
        response = await llm.chat(
            [{"role": "system", "content": system_prompt}, *working],
            tools=registry.schemas(),
        )
        calls = response.get("tool_calls") or []
        content_text = _text_of(response.get("content"))

        if not calls:
            text = content_text or FALLBACK
            await add_message(db, session_id=session.id, role="assistant", content=text)
            await db.commit()
            return text

        working.append(
            {
                "role": "assistant",
                "content": content_text,
                "tool_calls": calls,
            }
        )

        for call in calls:
            name, args, call_id = _call_parts(call)
            result = await registry.execute(name, args, ctx)
            logger.info(
                "Tool call completed",
                extra={
                    "session_id": session.id,
                    "tool": name,
                    "iteration": iteration,
                    "ok": bool(result.get("ok")),
                    "error": result.get("error"),
                },
            )
            working.append(tool_result_message(call_id, name, result))
            await add_message(
                db,
                session_id=session.id,
                role="tool",
                content=json.dumps(
                    {"tool": name, "args": args, "result": result}, ensure_ascii=False
                )[:4000],
            )
        await db.commit()

    logger.warning(
        "Tool iteration budget exhausted", extra={"session_id": session.id}
    )
    await add_message(db, session_id=session.id, role="assistant", content=FALLBACK)
    await db.commit()
    return FALLBACK
