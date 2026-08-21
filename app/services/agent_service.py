from typing import Any, Dict, List, Optional
import httpx
import openai
from pydantic import BaseModel, Field
from langchain_openrouter import ChatOpenRouter
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain.agents import create_agent
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from app.core.config import Settings
from app.core.logger import logger
from app.utils.exceptions import (
    DeepSeekAPIException,
    DeepSeekTimeoutException,
    RateLimitException,
)
from app.utils.tool import web_search, document_search
from dataclasses import dataclass, field
import re
from app.services.prompt_service import PromptService


@dataclass
class NormalizedStreamChunk:
    text: str = ""
    reasoning: str = ""
    tool_call: Optional[Dict[str, Any]] = None


class StreamEventNormalizer:
    """Normalizes provider-specific LangChain stream chunks into unified text, reasoning, and tool_call parts."""

    INTERNAL_MARKERS = [
        "<think>",
        "</think>",
        "<tool_call>",
        "</tool_call>",
        "<function>",
        "</function>",
        "<|DSML|>",
        "<｜DSML｜",
    ]

    @classmethod
    def normalize_chunk(cls, chunk: Any) -> NormalizedStreamChunk:
        norm = NormalizedStreamChunk()
        if not chunk:
            return norm

        content = getattr(chunk, "content", None)

        if isinstance(content, str):
            norm.text = content
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    if isinstance(block, str):
                        norm.text += block
                    continue

                b_type = block.get("type")
                if b_type == "text":
                    norm.text += block.get("text", "")
                elif b_type in {"reasoning", "thinking", "reasoning_content"}:
                    norm.reasoning += (
                        block.get("text", "")
                        or block.get("reasoning", "")
                        or block.get("content", "")
                    )

        additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
        reasoning = (
            additional_kwargs.get("reasoning_content")
            or additional_kwargs.get("reasoning")
            or additional_kwargs.get("reasoning_details")
        )
        if isinstance(reasoning, str):
            norm.reasoning += reasoning

        # Filter out explicit protocol markers from text
        for marker in cls.INTERNAL_MARKERS:
            if marker in norm.text:
                norm.text = norm.text.replace(marker, "")

        return norm


def clean_thinking_text(text: str) -> str:
    """Final sanitizer layer to clean leftover protocol markers from complete response."""
    if not text:
        return text
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<\|DSML\|>[\s\S]*?</\|DSML\|>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<function>[\s\S]*?</function>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<tool_call>[\s\S]*?</tool_call>', '', text, flags=re.IGNORECASE)
    return text.strip()


class TokenAndReasoningCallbackHandler(AsyncCallbackHandler):
    """Callback handler to accumulate token usage and reasoning details across agent steps."""
    
    def __init__(self) -> None:
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.last_reasoning = None

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for generations in response.generations:
            for gen in generations:
                message = getattr(gen, "message", None)
                if message is not None:
                    usage = getattr(message, "usage_metadata", None)
                    if usage is not None:
                        self.total_prompt_tokens += usage.get("input_tokens", 0)
                        self.total_completion_tokens += usage.get("output_tokens", 0)
                        self.total_tokens += usage.get("total_tokens", 0)
                    else:
                        metadata = message.response_metadata
                        token_usage = metadata.get("token_usage", {})
                        self.total_prompt_tokens += token_usage.get("prompt_tokens", 0)
                        self.total_completion_tokens += token_usage.get("completion_tokens", 0)
                        self.total_tokens += token_usage.get("total_tokens", 0)
                    
                    reasoning = (
                        message.additional_kwargs.get("reasoning_details")
                        or message.additional_kwargs.get("reasoning_content")
                        or message.additional_kwargs.get("reasoning")
                    )
                    if reasoning is not None:
                        self.last_reasoning = reasoning


# ------------------------------------------------------------------
# LLM Provider Registry Functions
# ------------------------------------------------------------------
PROVIDER_REGISTRY: Dict[str, Any] = {}

def register_provider(name: str):
    def decorator(fn):
        PROVIDER_REGISTRY[name.lower()] = fn
        return fn
    return decorator


@register_provider("anthropic")
def create_anthropic_model(
    *,
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    http_async_client=None,
    **kwargs
):
    try:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ImportError:
        logger.warning("langchain_anthropic not installed. Falling back to ChatOpenRouter.")
        return ChatOpenRouter(
            model=model,
            openrouter_api_key=api_key,
            streaming=True,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=600,
            http_async_client=http_async_client,
        )


@register_provider("gemini")
def create_gemini_model(
    *,
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    http_async_client=None,
    **kwargs
):
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            google_api_key=api_key,
            model=model,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    except ImportError:
        logger.warning("langchain_google_genai not installed. Falling back to ChatOpenRouter.")
        return ChatOpenRouter(
            model=model,
            openrouter_api_key=api_key,
            streaming=True,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=600,
            http_async_client=http_async_client,
        )


@register_provider("openai")
def create_openai_model(
    *,
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    http_async_client=None,
    **kwargs
):
    return ChatOpenAI(
        api_key=api_key,
        model=model,
        streaming=True,
        temperature=temperature,
        max_tokens=max_tokens,
        http_async_client=http_async_client,
    )


@register_provider("openai-compatible")
@register_provider("custom")
def create_openai_compatible_model(
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    http_async_client=None,
    **kwargs
):
    if base_url:
        return ChatOpenAI(
            api_key=api_key,
            model=model,
            base_url=base_url,
            streaming=True,
            temperature=temperature,
            max_tokens=max_tokens,
            http_async_client=http_async_client,
        )
    return ChatOpenAI(
        api_key=api_key,
        model=model,
        streaming=True,
        temperature=temperature,
        max_tokens=max_tokens,
        http_async_client=http_async_client,
    )


@register_provider("openrouter")
def create_openrouter_model(
    *,
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    http_async_client=None,
    **kwargs
):
    return ChatOpenRouter(
        model=model,
        openrouter_api_key=api_key,
        streaming=True,
        reasoning={"effort": "medium"},
        temperature=temperature,
        max_tokens=max_tokens,
        request_timeout=600,
        http_async_client=http_async_client
    )


class AgentService:
    """Service to handle agent creation and communication using dynamic User LLM Configuration & System Prompts."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.prompt_service = PromptService()
        self.default_system_prompt = self.prompt_service.get_system_prompt()
        self.tools = [web_search, document_search]

    @property
    def system_prompt(self) -> str:
        """Exposes the default system prompt for fallback compatibility."""
        return self.default_system_prompt

    def _get_llm_model(self, llm_config: Optional[Dict[str, Any]] = None):
        """Constructs an LLM model instance using registered provider functions."""
        llm_async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=None, write=30.0, pool=30.0)
        )
        print("LLM Config==>", llm_config)

        if not llm_config or not llm_config.get("api_key"):
            raise DeepSeekAPIException(
                message="LLM configuration not found for user. Please configure your LLM API Key and Model at /llm-config.",
                status_code=400
            )

        config_type = llm_config.get("config_type", "provider")
        api_key = llm_config.get("api_key", "").strip()
        if not api_key:
            raise DeepSeekAPIException(
                message="API key missing in user LLM configuration.",
                status_code=400
            )

        temperature = float(llm_config.get("temperature", 0.7)) if llm_config.get("temperature") is not None else 0.7
        max_tokens = int(llm_config.get("max_tokens", 1000)) if llm_config.get("max_tokens") is not None else 1000

        if config_type == "provider":
            provider_name = (llm_config.get("provider") or "openrouter").lower()
            model_name = llm_config.get("default_model") or llm_config.get("model")
            if not model_name:
                raise DeepSeekAPIException(
                    message="Model name missing in user LLM configuration.",
                    status_code=400
                )

            creator_fn = PROVIDER_REGISTRY.get(provider_name, PROVIDER_REGISTRY.get("openai"))
            logger.info(f"Instantiating model using registered provider '{provider_name}' | model: '{model_name}' | temp: {temperature} | max_tokens: {max_tokens}")
            return creator_fn(
                api_key=api_key,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                http_async_client=llm_async_client
            )

        elif config_type == "custom":
            base_url = llm_config.get("base_url")
            model_name = llm_config.get("model")
            if not base_url or not model_name:
                raise DeepSeekAPIException(
                    message="Custom LLM configuration requires both 'base_url' and 'model'.",
                    status_code=400
                )

            creator_fn = PROVIDER_REGISTRY.get("openai-compatible")
            logger.info(f"Instantiating openai-compatible model for custom endpoint: '{base_url}' | model: '{model_name}' | temp: {temperature} | max_tokens: {max_tokens}")
            return creator_fn(
                api_key=api_key,
                model=model_name,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens,
                http_async_client=llm_async_client
            )
        else:
            raise DeepSeekAPIException(
                message=f"Unsupported configuration type '{config_type}'.",
                status_code=400
            )

    def _format_system_prompt(self, prompt: str) -> str:
        """Dynamically injects current date and time reference into system prompt."""
        from datetime import datetime
        try:
            import pytz
            now = datetime.now(pytz.timezone("Asia/Kolkata"))
        except Exception:
            now = datetime.utcnow()

        current_time_str = now.strftime("%A, %d %B %Y, %I:%M %p %Z")

        if "{current_time_str}" in prompt:
            return prompt.replace("{current_time_str}", current_time_str)

        if "Current Date & Time Reference:" not in prompt and "Current Time:" not in prompt:
            return f"{prompt}\n\n[Current Date & Time Reference: {current_time_str}]"

        return prompt

    def _create_agent_executor(
        self,
        llm_config: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None
    ):
        """Compiles an agent executor with specified model configuration and system prompt."""
        model = self._get_llm_model(llm_config)
        prompt = self.prompt_service.get_system_prompt(behavior=system_prompt)

        try:
            from langchain.agents.middleware import SummarizationMiddleware
            middleware_list = [
                SummarizationMiddleware(
                    model=model,
                    trigger=("messages", 50),
                    keep=("messages", 20)
                )
            ]
        except Exception as mw_err:
            logger.warning(f"SummarizationMiddleware import warning: {mw_err}")
            middleware_list = []

        return create_agent(
            model=model,
            tools=self.tools,
            system_prompt=prompt,
            middleware=middleware_list,
            debug=False
        )

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[Any]:
        lc_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            reasoning_details = msg.get("reasoning_details")
            
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                kwargs = {}
                if reasoning_details is not None:
                    kwargs["reasoning_details"] = reasoning_details
                lc_messages.append(AIMessage(content=content, additional_kwargs=kwargs))
        return lc_messages

    async def astream_chat_response(
        self,
        messages: List[Dict[str, Any]],
        llm_config: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None
    ):
        """Streams multi-event updates (tool execution status, reasoning deltas, text deltas, final result)."""
        agent_executor = self._create_agent_executor(llm_config=llm_config, system_prompt=system_prompt)
        lc_messages = self._convert_messages(messages)
        callback_handler = TokenAndReasoningCallbackHandler()

        full_content = ""
        full_reasoning = ""

        try:
            logger.info("Streaming agent execution events...")
            async for event in agent_executor.astream_events(
                {"messages": lc_messages},
                version="v2",
                config={"callbacks": [callback_handler]}
            ):
                event_kind = event.get("event")
                event_name = event.get("name", "")

                if event_kind == "on_tool_start":
                    tool_input = event.get("data", {}).get("input")
                    query_str = ""
                    if isinstance(tool_input, dict):
                        query_str = tool_input.get("query") or tool_input.get("input") or str(tool_input)
                    elif isinstance(tool_input, str):
                        query_str = tool_input

                    user_status = f"Searching using {event_name}..."
                    if event_name == "web_search":
                        user_status = f"Searching web for '{query_str}'..." if query_str else "Searching web..."
                    elif event_name == "document_search":
                        user_status = f"Searching knowledge base for '{query_str}'..." if query_str else "Searching knowledge base..."

                    yield {
                        "type": "status",
                        "status": "searching",
                        "tool": event_name,
                        "message": user_status,
                        "query": query_str
                    }

                elif event_kind == "on_tool_end":
                    yield {
                        "type": "status",
                        "status": "tool_completed",
                        "tool": event_name,
                        "message": f"Finished {event_name} execution"
                    }

                elif event_kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        norm = StreamEventNormalizer.normalize_chunk(chunk)

                        if norm.text:
                            full_content += norm.text
                            yield {"type": "text_delta", "delta": norm.text}

                        if norm.reasoning:
                            full_reasoning += norm.reasoning
                            yield {"type": "reasoning_delta", "delta": norm.reasoning}

                elif event_kind == "on_chat_model_end":
                    output = event.get("data", {}).get("output")
                    if output:
                        usage = getattr(output, "usage_metadata", None)
                        if usage and isinstance(usage, dict):
                            callback_handler.total_prompt_tokens += usage.get("input_tokens", 0)
                            callback_handler.total_completion_tokens += usage.get("output_tokens", 0)
                            callback_handler.total_tokens += usage.get("total_tokens", 0)
                        else:
                            meta = getattr(output, "response_metadata", {}) or {}
                            toks = meta.get("token_usage", {}) or meta.get("usage", {})
                            if toks and isinstance(toks, dict):
                                callback_handler.total_prompt_tokens += toks.get("prompt_tokens", 0) or toks.get("input_tokens", 0)
                                callback_handler.total_completion_tokens += toks.get("completion_tokens", 0) or toks.get("output_tokens", 0)
                                callback_handler.total_tokens += toks.get("total_tokens", 0)

            # Fallback calculation if provider does not report token usage metadata in streaming
            if callback_handler.total_prompt_tokens == 0:
                estimated_prompt = sum(len(str(m.get("content", ""))) // 4 for m in messages)
                callback_handler.total_prompt_tokens = max(12, estimated_prompt)

            if callback_handler.total_completion_tokens == 0:
                estimated_completion = len(full_content) // 4
                callback_handler.total_completion_tokens = max(5, estimated_completion)

            callback_handler.total_tokens = callback_handler.total_prompt_tokens + callback_handler.total_completion_tokens

            usage_dict = {
                "prompt_tokens": callback_handler.total_prompt_tokens,
                "completion_tokens": callback_handler.total_completion_tokens,
                "total_tokens": callback_handler.total_tokens
            }

            clean_content = clean_thinking_text(full_content)

            yield {
                "type": "done",
                "message": clean_content,
                "reasoning_details": callback_handler.last_reasoning or full_reasoning or None,
                "usage": usage_dict
            }

        except Exception as exc:
            logger.exception(f"Error in astream_chat_response: {exc}")
            fallback_msg = "Server issue: Please contact the chatbot owner."
            yield {
                "type": "text_delta",
                "delta": fallback_msg
            }
            yield {
                "type": "done",
                "message": fallback_msg,
                "reasoning_details": None,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }

    async def get_chat_response(
        self,
        messages: List[Dict[str, Any]],
        llm_config: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Calls the agent workflow and returns final response message and metadata."""
        try:
            agent_executor = self._create_agent_executor(llm_config=llm_config, system_prompt=system_prompt)
            lc_messages = self._convert_messages(messages)

            logger.info("Invoking compiled agent workflow...")
            callback_handler = TokenAndReasoningCallbackHandler()
            
            response = await agent_executor.ainvoke(
                {"messages": lc_messages},
                config={"callbacks": [callback_handler]}
            )
            
            if isinstance(response, dict) and "messages" in response:
                final_message = response["messages"][-1]
                content = final_message.content
            else:
                content = response.get("output", "")

            content = clean_thinking_text(content)

            if callback_handler.total_prompt_tokens == 0:
                estimated_prompt = sum(len(str(m.get("content", ""))) // 4 for m in messages)
                callback_handler.total_prompt_tokens = max(12, estimated_prompt)

            if callback_handler.total_completion_tokens == 0:
                estimated_completion = len(content) // 4
                callback_handler.total_completion_tokens = max(5, estimated_completion)

            callback_handler.total_tokens = callback_handler.total_prompt_tokens + callback_handler.total_completion_tokens

            usage_dict = {
                "prompt_tokens": callback_handler.total_prompt_tokens,
                "completion_tokens": callback_handler.total_completion_tokens,
                "total_tokens": callback_handler.total_tokens
            }
            
            return {
                "message": content,
                "usage": usage_dict,
                "reasoning_details": callback_handler.last_reasoning
            }

        except Exception as exc:
            logger.exception(f"Unexpected error in get_chat_response: {exc}")
            fallback_msg = "Server issue: Please contact the chatbot owner."
            return {
                "message": fallback_msg,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "reasoning_details": None
            }
