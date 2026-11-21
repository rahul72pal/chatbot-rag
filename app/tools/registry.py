"""Tool registry: the model proposes a call, the backend validates and decides.

Every tool invocation goes through three gates:
1. Pydantic schema validation of the arguments the model produced.
2. Idempotency for mutating tools, so a retried or repeated call writes once.
3. A timeout budget, so a slow backend cannot hang the spoken turn.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logger import logger
from app.db.database import SessionLocal
from app.db.models import ToolExecution


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def set(
        self, key: str, result: dict[str, Any], *, tool: str, args: dict[str, Any]
    ) -> None: ...


class SqlIdempotencyStore:
    """Persist cached tool results in the same database as the sessions."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    async def get(self, key: str) -> dict[str, Any] | None:
        async with SessionLocal() as db:
            row = await db.scalar(
                select(ToolExecution).where(ToolExecution.idempotency_key == key)
            )
            return dict(row.result) if row is not None else None

    async def set(
        self, key: str, result: dict[str, Any], *, tool: str, args: dict[str, Any]
    ) -> None:
        async with SessionLocal() as db:
            db.add(
                ToolExecution(
                    idempotency_key=key,
                    session_id=self.session_id,
                    tool=tool,
                    args=args,
                    result=result,
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                # A concurrent duplicate won the race; the stored result wins.
                await db.rollback()


class MemoryIdempotencyStore:
    """Small store used by tests and single-process demos."""

    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        cached = self._data.get(key)
        return dict(cached) if cached is not None else None

    async def set(
        self, key: str, result: dict[str, Any], *, tool: str, args: dict[str, Any]
    ) -> None:
        self._data[key] = dict(result)


@dataclass
class ToolContext:
    session_id: str
    user_id: str
    store: IdempotencyStore
    confirmed: bool = False
    chatbot_id: str | None = None


Handler = Callable[[BaseModel, ToolContext], Awaitable[dict[str, Any]]]


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler
    mutating: bool = False


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.args_model.model_json_schema(),
                },
            }
            for t in self._tools.values()
        ]

    @staticmethod
    def _parse(raw_args: str | dict[str, Any], model: type[BaseModel]) -> BaseModel:
        if isinstance(raw_args, dict):
            return model.model_validate(raw_args)
        return model.model_validate_json(raw_args or "{}")

    async def execute(
        self, name: str, raw_args: str | dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": "unknown_tool"}

        # 1. Validate arguments. The model never gets to pass unchecked values.
        try:
            args = self._parse(raw_args, tool.args_model)
        except ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first.get("loc", ()))
            return {
                "ok": False,
                "error": "invalid_arguments",
                "detail": f"{location}: {first.get('msg')}",
            }

        # 2. Idempotency for mutating tools: session + tool + canonical args.
        key: str | None = None
        if tool.mutating:
            payload = f"{ctx.session_id}:{name}:{args.model_dump_json()}"
            key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            cached = await ctx.store.get(key)
            if cached is not None:
                logger.info(
                    "Idempotent tool replay",
                    extra={"session_id": ctx.session_id, "tool": name},
                )
                return cached

        # 3. Execute inside the timeout budget. Mutating work survives a
        # barge-in cancellation so a database write cannot be half-aborted;
        # its completion still records the idempotency result.
        async def execute_handler() -> dict[str, Any]:
            value = await tool.handler(args, ctx)
            if not isinstance(value, dict):
                return {"ok": False, "error": "tool_failed"}
            if key is not None and value.get("ok"):
                await ctx.store.set(
                    key, value, tool=name, args=args.model_dump(mode="json")
                )
            return value

        task = asyncio.create_task(execute_handler()) if tool.mutating else None
        if task is not None:
            task.add_done_callback(_observe_mutating_task)
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task) if task else tool.handler(args, ctx),
                settings.TOOL_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Tool timed out",
                extra={"session_id": ctx.session_id, "tool": name},
            )
            return {"ok": False, "error": "tool_timeout"}
        except Exception:
            logger.exception(
                "Tool failed",
                extra={"session_id": ctx.session_id, "tool": name},
            )
            return {"ok": False, "error": "tool_failed"}

        if not isinstance(result, dict):
            return {"ok": False, "error": "tool_failed"}

        # Cache only completed writes. The mutating task already cached its result.
        return result


def _observe_mutating_task(task: asyncio.Task) -> None:
    """Retrieve exceptions from shielded writes after timeout or barge-in."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Shielded mutating tool failed")


def tool_result_message(call_id: str, name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Build the OpenAI-style tool message handed back to the model."""
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": json.dumps(result, ensure_ascii=False),
    }
