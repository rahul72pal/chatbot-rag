import json

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import settings
from app.core.orchestrator import FALLBACK, run_turn
from app.db.database import SessionLocal
from app.db.models import Message
from app.tools.registry import MemoryIdempotencyStore, Tool, ToolContext, ToolRegistry
from tests.conftest import make_session


class NoteArgs(BaseModel):
    text: str


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.seen = []

    async def chat(self, messages, tools=None):
        self.seen.append(messages)
        return self.responses.pop(0)


def tool_call(call_id="call-1", name="save_note", arguments=None):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments or {"text": "hi"})},
    }


@pytest.fixture
def registry():
    seen = []

    async def save_note(args: NoteArgs, ctx: ToolContext) -> dict:
        seen.append(args.text)
        return {"ok": True, "stored": args.text}

    reg = ToolRegistry()
    reg.register(Tool("save_note", "save", NoteArgs, save_note, mutating=True))
    reg.seen = seen
    return reg


async def run(session, llm, registry):
    ctx = ToolContext(
        session_id=session.id,
        user_id=session.user_id,
        store=MemoryIdempotencyStore(),
    )
    async with SessionLocal() as db:
        return await run_turn(db, session, "book me a table", llm, registry, ctx)


async def test_plain_answer_is_persisted():
    session = await make_session()
    llm = ScriptedLLM([{"role": "assistant", "content": "Sure, what date?"}])

    reply = await run(session, llm, ToolRegistry())

    assert reply == "Sure, what date?"
    async with SessionLocal() as db:
        rows = list((await db.scalars(
            select(Message).where(Message.session_id == session.id).order_by(Message.id)
        )).all())
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].content == "book me a table"


async def test_tool_result_is_fed_back_to_the_model(registry):
    session = await make_session()
    llm = ScriptedLLM([
        {"role": "assistant", "content": "", "tool_calls": [tool_call()]},
        {"role": "assistant", "content": "Done."},
    ])

    reply = await run(session, llm, registry)

    assert reply == "Done."
    assert registry.seen == ["hi"]
    tool_messages = [m for m in llm.seen[1] if m.get("role") == "tool"]
    assert tool_messages and json.loads(tool_messages[0]["content"])["ok"] is True
    assert tool_messages[0]["tool_call_id"] == "call-1"

    async with SessionLocal() as db:
        audit = list((await db.scalars(
            select(Message).where(
                Message.session_id == session.id, Message.role == "tool"
            )
        )).all())
    assert len(audit) == 1
    assert json.loads(audit[0].content)["tool"] == "save_note"


async def test_invalid_arguments_are_reported_back(registry):
    session = await make_session()
    llm = ScriptedLLM([
        {"role": "assistant", "content": "", "tool_calls": [tool_call(arguments={})]},
        {"role": "assistant", "content": "Could you repeat that?"},
    ])

    await run(session, llm, registry)

    tool_message = next(m for m in llm.seen[1] if m.get("role") == "tool")
    assert json.loads(tool_message["content"])["error"] == "invalid_arguments"
    assert registry.seen == []


async def test_unknown_tool_is_reported_back(registry):
    session = await make_session()
    llm = ScriptedLLM([
        {"role": "assistant", "content": "", "tool_calls": [tool_call(name="refund_everything")]},
        {"role": "assistant", "content": "I can't do that."},
    ])

    reply = await run(session, llm, registry)

    assert reply == "I can't do that."
    tool_message = next(m for m in llm.seen[1] if m.get("role") == "tool")
    assert json.loads(tool_message["content"])["error"] == "unknown_tool"


async def test_iteration_cap_stops_a_looping_model(registry, monkeypatch):
    monkeypatch.setattr(settings, "MAX_TOOL_ITERATIONS", 2)
    session = await make_session()
    llm = ScriptedLLM([
        {"role": "assistant", "content": "", "tool_calls": [tool_call("call-1", arguments={"text": "one"})]},
        {"role": "assistant", "content": "", "tool_calls": [tool_call("call-2", arguments={"text": "two"})]},
        {"role": "assistant", "content": "", "tool_calls": [tool_call("call-3", arguments={"text": "three"})]},
    ])

    reply = await run(session, llm, registry)

    assert reply == FALLBACK
    assert registry.seen == ["one", "two"]
    assert len(llm.seen) == 2


async def test_empty_model_output_uses_fallback():
    session = await make_session()
    llm = ScriptedLLM([{"role": "assistant", "content": "   "}])

    assert await run(session, llm, ToolRegistry()) == FALLBACK
