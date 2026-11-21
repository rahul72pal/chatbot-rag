"""Adapter for the existing user-configured LangChain chat model."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.providers.base import Message, Tool


class UserConfigLLM:
    """Use the app's existing provider registry with a user's voice model."""

    def __init__(self, agent_service: Any, user_config: dict[str, Any]):
        if not user_config:
            raise ValueError("User LLM configuration is required for voice chat.")

        config = dict(user_config)
        voice_model = config.get("voice_agent_model")
        if voice_model:
            if config.get("config_type", "provider") == "custom":
                config["model"] = voice_model
            else:
                config["default_model"] = voice_model
        # Older saved configurations can still run voice using their chat model.
        elif not (config.get("default_model") or config.get("model")):
            raise ValueError("Set voice_agent_model in the user's LLM configuration.")

        self.agent_service = agent_service
        self.user_config = config
        self.model = agent_service._get_llm_model(config)

    def _messages(self, messages: Sequence[Message]) -> list[Any]:
        return self.agent_service._convert_messages(list(messages))

    @staticmethod
    def _assistant_message(result: Any) -> Message:
        content = getattr(result, "content", "")
        tool_calls = getattr(result, "tool_calls", None)
        message: Message = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    async def chat(
        self, messages: Sequence[Message], tools: Sequence[Tool] | None = None
    ) -> Message:
        model = self.model.bind_tools(list(tools)) if tools else self.model
        result = await model.ainvoke(self._messages(messages))
        return self._assistant_message(result)

    async def chat_with_agent(
        self,
        messages: Sequence[Message],
        *,
        user_id: str,
        session_id: str,
        system_prompt: str,
        chatbot_id: str | None = None,
    ) -> Message:
        """Run the existing chatbot tools with the authenticated user's context."""
        from langchain.agents import create_agent

        from app.core.context import (
            current_chatbot_id,
            current_llm_config,
            current_user_id,
            current_voice_session_id,
        )
        from app.utils.tool import reset_search_counter

        user_token = current_user_id.set(user_id)
        chatbot_token = current_chatbot_id.set(chatbot_id)
        config_token = current_llm_config.set(self.user_config)
        session_token = current_voice_session_id.set(session_id)
        try:
            reset_search_counter()
            prompt = self.agent_service.prompt_service.get_system_prompt(behavior=system_prompt)
            agent = create_agent(
                model=self.model,
                tools=self.agent_service.tools,
                system_prompt=prompt,
                debug=False,
            )
            result = await agent.ainvoke(
                {"messages": self._messages(messages)},
                config={"recursion_limit": 10},
            )
            result_messages = result.get("messages", [])
            for message in reversed(result_messages):
                if getattr(message, "type", None) == "ai":
                    return self._assistant_message(message)
            return {"role": "assistant", "content": "Sorry, could you say that again?"}
        finally:
            current_llm_config.reset(config_token)
            current_voice_session_id.reset(session_token)
            current_chatbot_id.reset(chatbot_token)
            current_user_id.reset(user_token)

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        async for chunk in self.model.astream(self._messages(messages)):
            content = getattr(chunk, "content", "")
            if isinstance(content, str) and content:
                yield content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        yield part["text"]
