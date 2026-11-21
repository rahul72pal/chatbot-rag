import asyncio
import json

import pytest
from pydantic import BaseModel

from app.core.config import settings
from app.tools.registry import (
    MemoryIdempotencyStore,
    Tool,
    ToolContext,
    ToolRegistry,
)


class EchoArgs(BaseModel):
    value: int


class FailArgs(BaseModel):
    value: int


def make_ctx(store=None) -> ToolContext:
    return ToolContext(
        session_id="sess-1",
        user_id="user-1",
        store=store or MemoryIdempotencyStore(),
    )


@pytest.fixture
def calls():
    return {"count": 0}


@pytest.fixture
def registry(calls):
    async def echo(args: EchoArgs, ctx: ToolContext) -> dict:
        calls["count"] += 1
        return {"ok": True, "value": args.value, "n": calls["count"]}

    async def slow(args: EchoArgs, ctx: ToolContext) -> dict:
        await asyncio.sleep(2)
        return {"ok": True}

    async def boom(args: FailArgs, ctx: ToolContext) -> dict:
        raise RuntimeError("backend down")

    async def peek(args: EchoArgs, ctx: ToolContext) -> dict:
        calls["count"] += 1
        return {"ok": True, "n": calls["count"]}

    reg = ToolRegistry()
    reg.register_all([
        Tool("echo", "echo", EchoArgs, echo, mutating=True),
        Tool("peek", "peek", EchoArgs, peek),
        Tool("slow", "slow", EchoArgs, slow),
        Tool("boom", "boom", FailArgs, boom),
    ])
    return reg


async def test_unknown_tool_returns_error(registry):
    result = await registry.execute("nope", "{}", make_ctx())
    assert result == {"ok": False, "error": "unknown_tool"}


async def test_schema_exposed_for_every_tool(registry):
    names = {schema["function"]["name"] for schema in registry.schemas()}
    assert names == {"echo", "peek", "slow", "boom"}
    parameters = next(
        schema["function"]["parameters"]
        for schema in registry.schemas()
        if schema["function"]["name"] == "echo"
    )
    assert parameters["properties"]["value"]["type"] == "integer"


async def test_invalid_arguments_are_rejected_before_handler(registry, calls):
    result = await registry.execute("echo", json.dumps({"value": "not-a-number"}), make_ctx())
    assert result["ok"] is False
    assert result["error"] == "invalid_arguments"
    assert calls["count"] == 0


async def test_missing_argument_is_rejected(registry):
    result = await registry.execute("echo", "{}", make_ctx())
    assert result["error"] == "invalid_arguments"


async def test_mutating_tool_is_idempotent(registry, calls):
    ctx = make_ctx()
    args = json.dumps({"value": 4})

    first = await registry.execute("echo", args, ctx)
    second = await registry.execute("echo", args, ctx)

    assert first == second
    assert calls["count"] == 1


async def test_different_arguments_execute_again(registry, calls):
    ctx = make_ctx()
    await registry.execute("echo", json.dumps({"value": 1}), ctx)
    await registry.execute("echo", json.dumps({"value": 2}), ctx)
    assert calls["count"] == 2


async def test_non_mutating_tool_is_never_cached(registry, calls):
    ctx = make_ctx()
    await registry.execute("peek", json.dumps({"value": 1}), ctx)
    await registry.execute("peek", json.dumps({"value": 1}), ctx)
    assert calls["count"] == 2


async def test_tool_timeout_is_reported(registry, monkeypatch):
    monkeypatch.setattr(settings, "TOOL_TIMEOUT_S", 0.05)
    result = await registry.execute("slow", json.dumps({"value": 1}), make_ctx())
    assert result == {"ok": False, "error": "tool_timeout"}


async def test_tool_exception_is_contained(registry):
    result = await registry.execute("boom", json.dumps({"value": 1}), make_ctx())
    assert result == {"ok": False, "error": "tool_failed"}


async def test_dict_arguments_are_accepted(registry):
    result = await registry.execute("echo", {"value": 7}, make_ctx())
    assert result["ok"] is True
    assert result["value"] == 7
