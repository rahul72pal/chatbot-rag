import json
from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
from app.core.constants import ROLE_ASSISTANT, ROLE_USER
from app.core.dependencies import (
    get_conversation_service,
    get_agent_service,
    get_current_user,
    get_chatbot_service,
    get_user_llm_config_service
)
from app.core.logger import logger
from app.schemas.request import MessageRequest
from app.schemas.response import ChatResponse, TokenUsage
from app.services.conversation_service import ConversationService
from app.services.agent_service import AgentService
from app.services.chatbot_service import ChatbotService
from app.services.user_llm_config_service import UserLLMConfigService
from app.utils.helpers import measure_latency
from app.core.context import current_user_id, current_chatbot_id

router = APIRouter()

@router.post(
    "/message",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a chat message",
    description="Processes a user's prompt, retrieves context history, fetches a response from AgentService, and updates history."
)
async def post_message(
    payload: MessageRequest,
    current_user: dict = Depends(get_current_user),
    conversation_service: ConversationService = Depends(get_conversation_service),
    agent_service: AgentService = Depends(get_agent_service),
    chatbot_service: ChatbotService = Depends(get_chatbot_service),
    user_llm_config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
) -> ChatResponse:
    """Endpoint to interact with the chatbot backend."""
    user_id = current_user["id"]
    
    with measure_latency() as get_duration:
        # 1. Determine conversation and chatbot ID
        if payload.conversation_id is None:
            chatbot_id = payload.chatbot_id
            if not chatbot_id:
                user_chatbots = await chatbot_service.get_user_chatbots(user_id=user_id)
                if user_chatbots:
                    chatbot = user_chatbots[0]
                    chatbot_id = chatbot["id"]
                else:
                    from app.schemas.chatbot import ChatbotCreate
                    chatbot = await chatbot_service.create_chatbot(
                        user_id=user_id,
                        data=ChatbotCreate(
                            name="Default Assistant",
                            description="Default Assistant for testing LLM config",
                            welcome_message="Hi! How can I help you today?",
                            system_prompt="You are a helpful AI customer support agent.",
                            model="gpt-3.5-turbo",
                            temperature=0.7,
                            max_tokens=1000
                        )
                    )
                    chatbot_id = chatbot["id"]
            else:
                chatbot = await chatbot_service.get_chatbot(chatbot_id=chatbot_id, user_id=user_id)
                if not chatbot:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Chatbot not found or access denied."
                    )
            conversation_id = await conversation_service.create_conversation(
                user_id=user_id,
                chatbot_id=chatbot_id,
                title=f"Chat with {chatbot.get('name', 'Assistant')}"
            )
            conv = await conversation_service.get_conversation(conversation_id=conversation_id, user_id=user_id)
        else:
            conversation_id = payload.conversation_id
            conv = await conversation_service.get_conversation(conversation_id=conversation_id, user_id=user_id)
            if not conv:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found or access denied."
                )
            chatbot_id = conv["chatbot_id"]
            chatbot = await chatbot_service.get_chatbot(chatbot_id=chatbot_id, user_id=user_id)
            if not chatbot:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chatbot not found or access denied."
                )

        current_user_id.set(user_id)
        current_chatbot_id.set(chatbot_id)

        logger.info(f"Incoming chat request for conversation: {conversation_id} (chatbot: {chatbot_id})")

        # Add user's message to history
        await conversation_service.add_message(
            conversation_id=conversation_id,
            role=ROLE_USER,
            content=payload.message
        )

        history = await conversation_service.get_history(conversation_id)

        # Resolve system prompt: conversation > chatbot > prompt service default
        system_prompt = (conv and conv.get("system_prompt")) or (chatbot and chatbot.get("system_prompt"))
        if not system_prompt or not str(system_prompt).strip():
            system_prompt = agent_service.default_system_prompt

        # Resolve LLM Config: chatbot llm_config_id > single user_llm_config document
        llm_config = None
        llm_config_id = chatbot.get("llm_config_id") if chatbot else None
        if llm_config_id:
            llm_config = await user_llm_config_service.get_raw_config(config_id=llm_config_id, user_id=user_id)
        if not llm_config:
            llm_config = await user_llm_config_service.get_raw_user_config_by_user_id(user_id=user_id)

        if not llm_config or not llm_config.get("api_key"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LLM configuration not found for user. Please configure your API key and model at /llm-config."
            )

        full_history = history

        # Call AgentService
        result = await agent_service.get_chat_response(
            messages=full_history,
            llm_config=llm_config,
            system_prompt=system_prompt
        )
        
        response_text = result["message"]
        usage_data = result["usage"]
        reasoning_details = result.get("reasoning_details")

        completion_tokens = usage_data.get("completion_tokens", 0)
        await conversation_service.add_message(
            conversation_id=conversation_id,
            role=ROLE_ASSISTANT,
            content=response_text,
            tokens=completion_tokens,
            reasoning_details=reasoning_details
        )

        elapsed_time = get_duration()
        logger.info(
            f"Successfully processed message for conversation: {conversation_id} "
            f"| Latency: {elapsed_time:.4f}s | Status: Success"
        )

        return ChatResponse(
            success=True,
            conversation_id=conversation_id,
            message=response_text,
            usage=TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0)
            ),
            reasoning_details=reasoning_details
        )


@router.post(
    "/message/stream",
    summary="Send a chat message with streaming SSE response",
    description="Streams real-time events (tool execution loading status, reasoning, text deltas)."
)
async def post_message_stream(
    payload: MessageRequest,
    current_user: dict = Depends(get_current_user),
    conversation_service: ConversationService = Depends(get_conversation_service),
    agent_service: AgentService = Depends(get_agent_service),
    chatbot_service: ChatbotService = Depends(get_chatbot_service),
    user_llm_config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
):
    user_id = current_user["id"]

    if payload.conversation_id is None:
        chatbot_id = payload.chatbot_id
        if not chatbot_id:
            user_chatbots = await chatbot_service.get_user_chatbots(user_id=user_id)
            if user_chatbots:
                chatbot = user_chatbots[0]
                chatbot_id = chatbot["id"]
            else:
                from app.schemas.chatbot import ChatbotCreate
                chatbot = await chatbot_service.create_chatbot(
                    user_id=user_id,
                    data=ChatbotCreate(
                        name="Default Assistant",
                        description="Default Assistant for testing LLM config",
                        welcome_message="Hi! How can I help you today?",
                        system_prompt="You are a helpful AI customer support agent.",
                        model="gpt-3.5-turbo",
                        temperature=0.7,
                        max_tokens=1000
                    )
                )
                chatbot_id = chatbot["id"]
        else:
            chatbot = await chatbot_service.get_chatbot(chatbot_id=chatbot_id, user_id=user_id)
            if not chatbot:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chatbot not found or access denied."
                )
        conversation_id = await conversation_service.create_conversation(
            user_id=user_id,
            chatbot_id=chatbot_id,
            title=f"Chat with {chatbot.get('name', 'Assistant')}"
        )
        conv = await conversation_service.get_conversation(conversation_id=conversation_id, user_id=user_id)
    else:
        conversation_id = payload.conversation_id
        conv = await conversation_service.get_conversation(conversation_id=conversation_id, user_id=user_id)
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found or access denied."
            )
        chatbot_id = conv["chatbot_id"]
        chatbot = await chatbot_service.get_chatbot(chatbot_id=chatbot_id, user_id=user_id)
        if not chatbot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chatbot not found or access denied."
            )

    current_user_id.set(user_id)
    current_chatbot_id.set(chatbot_id)

    await conversation_service.add_message(
        conversation_id=conversation_id,
        role=ROLE_USER,
        content=payload.message
    )

    history = await conversation_service.get_history(conversation_id)

    # Resolve system prompt: conversation > chatbot > prompt service default
    system_prompt = (chatbot and chatbot.get("system_prompt"))
    if not system_prompt or not str(system_prompt).strip():
        system_prompt = agent_service.default_system_prompt

    # Resolve LLM Config: chatbot llm_config_id > single user_llm_config document
    llm_config = None
    llm_config_id = chatbot.get("llm_config_id") if chatbot else None
    if llm_config_id:
        llm_config = await user_llm_config_service.get_raw_config(config_id=llm_config_id, user_id=user_id)
    if not llm_config:
        llm_config = await user_llm_config_service.get_raw_user_config_by_user_id(user_id=user_id)

    if not llm_config or not llm_config.get("api_key"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM configuration not found for user. Please configure your API key and model at /llm-config."
        )

    full_history = history

    async def event_generator():
        yield f"data: {json.dumps({'type': 'conversation', 'conversation_id': conversation_id, 'chatbot_id': chatbot_id}, default=str)}\n\n"

        final_text = ""
        final_reasoning = None
        completion_tokens = 0

        async for event in agent_service.astream_chat_response(
            messages=full_history,
            llm_config=llm_config,
            system_prompt=system_prompt
        ):
            if event.get("type") == "done":
                final_text = event.get("message", "")
                final_reasoning = event.get("reasoning_details")
                usage = event.get("usage", {})
                completion_tokens = usage.get("completion_tokens", 0)
            yield f"data: {json.dumps(event, default=str)}\n\n"

        await conversation_service.add_message(
            conversation_id=conversation_id,
            role=ROLE_ASSISTANT,
            content=final_text,
            tokens=completion_tokens,
            reasoning_details=final_reasoning
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")
