import contextvars
from contextlib import asynccontextmanager
from typing import AsyncIterator

current_user_id = contextvars.ContextVar("current_user_id", default=None)
current_chatbot_id = contextvars.ContextVar("current_chatbot_id", default=None)
current_llm_config = contextvars.ContextVar("current_llm_config", default=None)
current_voice_session_id = contextvars.ContextVar("current_voice_session_id", default=None)
current_search_attempts = contextvars.ContextVar("current_search_attempts", default=0)


@asynccontextmanager
async def tool_runtime_context(
    *,
    user_id: str | None,
    session_id: str | None,
    llm_config: dict | None = None,
    chatbot_id: str | None = None,
) -> AsyncIterator[None]:
    """Expose the caller identity to tools that read context variables.

    Anonymous visitors have no LLM configuration of their own, so
    ``llm_config`` stays ``None`` and owner-only tools are not registered.
    """
    tokens = [
        (current_user_id, current_user_id.set(user_id)),
        (current_chatbot_id, current_chatbot_id.set(chatbot_id)),
        (current_llm_config, current_llm_config.set(llm_config)),
        (current_voice_session_id, current_voice_session_id.set(session_id)),
        (current_search_attempts, current_search_attempts.set(0)),
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
