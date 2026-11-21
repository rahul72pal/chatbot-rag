"""Wires the existing capabilities into the validated tool registry.

Anonymous visitors only get the booking tools. Knowledge-base search, web
search and preference memory need an authenticated owner, so they are only
registered when the caller has a verified user.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.memory import MAX_USER_MEMORY_ITEMS
from app.db.database import SessionLocal
from app.db.models import User, UserMemory
from app.tools.booking import booking_tools
from app.tools.registry import Tool, ToolContext, ToolRegistry


class SavePreferenceArgs(BaseModel):
    key: str = Field(min_length=1, max_length=64, description="Short preference name")
    value: str = Field(min_length=1, max_length=500, description="Preference value to remember")


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=500)


async def save_preference(args: SavePreferenceArgs, ctx: ToolContext) -> dict:
    if not ctx.user_id:
        return {"ok": False, "error": "memory_consent_required"}

    key = args.key.strip().lower()
    value = args.value.strip()
    if not key or not value:
        return {"ok": False, "error": "invalid_preference"}

    async with SessionLocal() as db:
        user = await db.get(User, ctx.user_id)
        if user is None or not user.memory_consent:
            return {"ok": False, "error": "memory_consent_required"}

        memory = await db.scalar(
            select(UserMemory).where(
                UserMemory.user_id == ctx.user_id, UserMemory.key == key
            )
        )
        if memory is None:
            db.add(UserMemory(user_id=ctx.user_id, key=key, value=value))
        else:
            memory.value = value

        await db.flush()
        total = await db.scalar(
            select(func.count(UserMemory.id)).where(UserMemory.user_id == ctx.user_id)
        )
        if int(total or 0) > MAX_USER_MEMORY_ITEMS:
            oldest = list((await db.scalars(
                select(UserMemory)
                .where(UserMemory.user_id == ctx.user_id)
                .order_by(UserMemory.id)
                .limit(int(total or 0) - MAX_USER_MEMORY_ITEMS)
            )).all())
            for item in oldest:
                await db.delete(item)
        await db.commit()

    return {"ok": True, "saved": key}


async def document_search(args: SearchArgs, ctx: ToolContext) -> dict:
    from app.services.qdrant_service import qdrant_service
    from app.core.context import current_chatbot_id, current_user_id

    cid = getattr(ctx, "chatbot_id", None) or current_chatbot_id.get(None)
    uid = getattr(ctx, "user_id", None) or current_user_id.get(None)

    try:
        docs = await qdrant_service.similarity_search(
            query=args.query,
            limit=4,
            chatbot_id=cid,
            user_id=uid if not cid else None,
        )
        if not docs:
            return {"ok": True, "results": "No relevant documents found for this chatbot."}
        formatted = "\n\n".join(
            f"Document: {d.get('filename', 'Unknown')}\n{d.get('text', '')}"
            for d in docs
        )
        return {"ok": True, "results": formatted}
    except Exception as exc:
        return {"ok": False, "error": f"Document search failed: {exc}"}


async def web_search(args: SearchArgs, ctx: ToolContext) -> dict:
    from app.utils.tool import web_search as langchain_web_search

    result = await langchain_web_search.ainvoke({"query": args.query})
    text = result if isinstance(result, str) else str(result)
    if text.startswith("Error executing web search"):
        return {"ok": False, "error": "tool_failed"}
    return {"ok": True, "results": text}


search_tools = [
    Tool(
        "document_search",
        "Search the owner's uploaded documents. Use for policy, FAQ or document questions.",
        SearchArgs,
        document_search,
    ),
    Tool(
        "web_search",
        "Search the public web for current information not covered by the documents.",
        SearchArgs,
        web_search,
    ),
]

preference_tools = [
    Tool(
        "save_preference",
        "Save a preference only when the user explicitly asks you to remember it.",
        SavePreferenceArgs,
        save_preference,
        mutating=True,
    ),
]


def build_registry(*, authenticated: bool, allow_search: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_all(booking_tools)
    if authenticated or allow_search:
        registry.register_all(search_tools)
    if authenticated:
        registry.register_all(preference_tools)
    return registry
