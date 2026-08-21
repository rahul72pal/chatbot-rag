import json
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from typing import List
from datetime import datetime
from uuid import uuid4
from app.core.dependencies import (
    get_current_user,
    get_chatbot_service,
    get_agent_service,
    get_qdrant_service,
    get_conversation_service,
    get_user_llm_config_service
)
from app.services.chatbot_service import ChatbotService
from app.services.agent_service import AgentService
from app.services.qdrant_service import QdrantService
from app.services.conversation_service import ConversationService
from app.services.user_llm_config_service import UserLLMConfigService
from app.schemas.chatbot import ChatbotCreate, ChatbotUpdate, ChatbotResponse
from app.core.logger import logger

from app.core.context import current_user_id, current_chatbot_id

router = APIRouter(prefix="/chatbot")

@router.post(
    "",
    response_model=ChatbotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom chatbot",
    description="Registers a new custom chatbot associated with the authenticated user."
)
async def create_chatbot(
    payload: ChatbotCreate,
    current_user: dict = Depends(get_current_user),
    chatbot_service: ChatbotService = Depends(get_chatbot_service)
) -> ChatbotResponse:
    user_id = current_user["id"]
    chatbot = await chatbot_service.create_chatbot(user_id=user_id, data=payload)
    return chatbot


@router.get(
    "",
    response_model=List[ChatbotResponse],
    summary="List all custom chatbots owned by the user",
    description="Retrieves a list of all chatbots created by the authenticated user."
)
async def list_chatbots(
    current_user: dict = Depends(get_current_user),
    chatbot_service: ChatbotService = Depends(get_chatbot_service)
) -> List[ChatbotResponse]:
    user_id = current_user["id"]
    chatbots = await chatbot_service.get_user_chatbots(user_id=user_id)
    return chatbots


@router.get(
    "/stats/summary",
    summary="Get user dashboard & chatbot statistics",
    description="Aggregates metrics for chatbots, conversations, messages, and documents owned by the user."
)
async def get_dashboard_stats(
    request: Request,
    current_user: dict = Depends(get_current_user)
) -> dict:
    user_id = current_user["id"]
    mongo_db = request.app.state.mongo_db

    chatbots_col = mongo_db["chatbots"]
    conversations_col = mongo_db["conversations"]
    documents_col = mongo_db["documents"]

    total_chatbots = await chatbots_col.count_documents({"user_id": user_id})
    active_chatbots = await chatbots_col.count_documents({"user_id": user_id, "$or": [{"status": "active"}, {"status": {"$exists": False}}]})

    total_conversations = await conversations_col.count_documents({"user_id": user_id})

    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$project": {"message_count": {"$size": {"$ifNull": ["$messages", []]}}}},
        {"$group": {"_id": None, "total_messages": {"$sum": "$message_count"}}}
    ]
    cursor = conversations_col.aggregate(pipeline)
    total_messages = 0
    async for doc in cursor:
        total_messages = doc.get("total_messages", 0)

    # Fallback message count from messages collection if 0
    if total_messages == 0:
        total_messages = await mongo_db["messages"].count_documents({"user_id": user_id})

    total_documents = await documents_col.count_documents({"user_id": user_id})

    return {
        "total_chatbots": total_chatbots,
        "active_chatbots": active_chatbots,
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "total_documents": total_documents
    }


@router.get(
    "/{chatbot_id}",
    response_model=ChatbotResponse,
    summary="Get a chatbot by ID",
    description="Retrieves details of a chatbot. Access is allowed if the chatbot is public, or if it belongs to the authenticated user."
)
async def get_chatbot(
    chatbot_id: str,
    current_user: dict = Depends(get_current_user),
    chatbot_service: ChatbotService = Depends(get_chatbot_service)
) -> ChatbotResponse:
    user_id = current_user["id"]
    chatbot = await chatbot_service.get_chatbot(chatbot_id=chatbot_id, user_id=user_id)
    if not chatbot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatbot not found or you do not have permission to access it."
        )
    return chatbot


@router.put(
    "/{chatbot_id}",
    response_model=ChatbotResponse,
    summary="Update a chatbot by ID",
    description="Updates existing configurations for a chatbot owned by the user."
)
async def update_chatbot(
    chatbot_id: str,
    payload: ChatbotUpdate,
    current_user: dict = Depends(get_current_user),
    chatbot_service: ChatbotService = Depends(get_chatbot_service)
) -> ChatbotResponse:
    user_id = current_user["id"]
    chatbot = await chatbot_service.update_chatbot(chatbot_id=chatbot_id, user_id=user_id, data=payload)
    if not chatbot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatbot not found, or you do not have permission to update it."
        )
    return chatbot


@router.get(
    "/public/{chatbot_id}",
    response_model=ChatbotResponse,
    summary="Public endpoint to get chatbot configuration for script tag embeds",
    description="Allows embedding script tags to retrieve public appearance & welcome configurations without auth headers."
)
async def get_public_chatbot(
    chatbot_id: str,
    chatbot_service: ChatbotService = Depends(get_chatbot_service)
) -> ChatbotResponse:
    chatbot = await chatbot_service.get_public_chatbot(chatbot_id=chatbot_id)
    if not chatbot:
        return ChatbotResponse(
            id=chatbot_id,
            user_id="demo-user",
            name="Support Assistant",
            description="Hi! How can I help you today?",
            welcome_message="Hi! How can I help you today?",
            system_prompt="You are a helpful AI customer support agent.",
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=1000,
            is_public=True,
            theme_color="#4f46e5",
            avatar_icon="support",
            avatar_url="support",
            position="right",
            bubble_style="rounded",
            open_automatically=False,
            pop_after_seconds=3,
            show_welcome_tooltip=True,
            created_at=datetime.utcnow()
        )
    return chatbot


@router.post(
    "/public/{chatbot_id}/chat",
    summary="Public widget chat endpoint",
    description="Allows website visitors to interact with embedded chatbot, retrieves full conversation context from MongoDB, and auto-summarizes after 50 messages."
)
async def public_chatbot_chat(
    chatbot_id: str,
    payload: dict,
    request: Request,
    chatbot_service: ChatbotService = Depends(get_chatbot_service),
    agent_service: AgentService = Depends(get_agent_service),
    qdrant_service: QdrantService = Depends(get_qdrant_service),
    conversation_service: ConversationService = Depends(get_conversation_service),
    user_llm_config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
):
    chatbot = await chatbot_service.get_public_chatbot(chatbot_id=chatbot_id)
    bot_name = chatbot.get("name", "Support Assistant") if chatbot else "Support Assistant"
    owner_user_id = chatbot.get("user_id", "demo-user") if chatbot else "demo-user"

    # Bind scoping ContextVars for vector document retrieval isolation
    current_chatbot_id.set(chatbot_id)
    current_user_id.set(owner_user_id)

    user_message = payload.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Retrieve or initialize conversation_id
    req_conv_id = payload.get("conversation_id")
    now = datetime.utcnow()

    mongo_db = request.app.state.mongo_db
    conversations_col = mongo_db["conversations"]
    messages_col = mongo_db["messages"]

    # 1. Handle Conversation creation (first message) / lookup (follow-up)
    if not req_conv_id:
        conversation_id = str(uuid4())
        conv_doc = {
            "_id": conversation_id,
            "conversation_id": conversation_id,
            "user_id": owner_user_id,
            "chatbot_id": chatbot_id,
            "title": f"Visitor Chat - {user_message[:30]}",
            "summary": None,
            "summarized_message_count": 0,
            "summary_version": 0,
            "status": "active",
            "created_at": now,
            "updated_at": now
        }
        await conversations_col.insert_one(conv_doc)
        conv = conv_doc
    else:
        conversation_id = req_conv_id
        existing_conv = await conversations_col.find_one({"_id": conversation_id})
        if existing_conv:
            await conversations_col.update_one(
                {"_id": conversation_id},
                {"$set": {"updated_at": now}}
            )
            conv = existing_conv
        else:
            conv_doc = {
                "_id": conversation_id,
                "conversation_id": conversation_id,
                "user_id": owner_user_id,
                "chatbot_id": chatbot_id,
                "title": f"Visitor Chat - {user_message[:30]}",
                "summary": None,
                "summarized_message_count": 0,
                "summary_version": 0,
                "status": "active",
                "created_at": now,
                "updated_at": now
            }
            await conversations_col.insert_one(conv_doc)
            conv = conv_doc

    # 2. Insert User Message document in MongoDB
    user_msg_id = str(uuid4())
    user_msg_doc = {
        "_id": user_msg_id,
        "conversation_id": conversation_id,
        "chatbot_id": chatbot_id,
        "user_id": owner_user_id,
        "role": "user",
        "content": user_message,
        "created_at": now
    }
    await messages_col.insert_one(user_msg_doc)

    # 3. Fetch history from MongoDB messages collection
    history = await conversation_service.get_history(conversation_id)

    # Resolve system prompt: conversation > chatbot > prompt service default
    system_prompt = (conv and conv.get("system_prompt")) or (chatbot and chatbot.get("system_prompt"))
    if not system_prompt or not str(system_prompt).strip():
        system_prompt = f"You are {bot_name}, a helpful AI customer support agent."

    # Resolve LLM Config: chatbot llm_config_id > single user_llm_config document
    llm_config = None
    llm_config_id = chatbot.get("llm_config_id") if chatbot else None
    if llm_config_id:
        llm_config = await user_llm_config_service.get_raw_config(config_id=llm_config_id, user_id=owner_user_id)
    if not llm_config:
        llm_config = await user_llm_config_service.get_raw_user_config_by_user_id(user_id=owner_user_id)

    bot_reply = "Server issue: Please contact the chatbot owner."
    try:
        res = await agent_service.get_chat_response(
            messages=history,
            llm_config=llm_config,
            system_prompt=system_prompt
        )
        if res and res.get("message"):
            bot_reply = res.get("message")
    except Exception as e:
        logger.error(f"LLM API call error: {e}")
        bot_reply = "Server issue: Please contact the chatbot owner."

    # 6. Insert Assistant Message document in MongoDB
    assistant_msg_id = str(uuid4())
    assistant_msg_doc = {
        "_id": assistant_msg_id,
        "conversation_id": conversation_id,
        "chatbot_id": chatbot_id,
        "user_id": owner_user_id,
        "role": "assistant",
        "content": bot_reply,
        "created_at": datetime.utcnow()
    }
    await messages_col.insert_one(assistant_msg_doc)

    return {
        "success": True,
        "message": bot_reply,
        "conversation_id": conversation_id,
        "chatbot_id": chatbot_id
    }


@router.post(
    "/public/{chatbot_id}/chat/stream",
    summary="Public widget chat streaming endpoint",
    description="Streams real-time events (tool execution loading status, reasoning, text deltas) using Server-Sent Events (SSE)."
)
async def public_chatbot_chat_stream(
    chatbot_id: str,
    payload: dict,
    request: Request,
    chatbot_service: ChatbotService = Depends(get_chatbot_service),
    agent_service: AgentService = Depends(get_agent_service),
    conversation_service: ConversationService = Depends(get_conversation_service),
    user_llm_config_service: UserLLMConfigService = Depends(get_user_llm_config_service)
):
    chatbot = await chatbot_service.get_public_chatbot(chatbot_id=chatbot_id)
    bot_name = chatbot.get("name", "Support Assistant") if chatbot else "Support Assistant"
    owner_user_id = chatbot.get("user_id", "demo-user") if chatbot else "demo-user"

    current_chatbot_id.set(chatbot_id)
    current_user_id.set(owner_user_id)

    user_message = payload.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    req_conv_id = payload.get("conversation_id")
    now = datetime.utcnow()

    mongo_db = request.app.state.mongo_db
    conversations_col = mongo_db["conversations"]
    messages_col = mongo_db["messages"]

    if not req_conv_id:
        conversation_id = str(uuid4())
        conv_doc = {
            "_id": conversation_id,
            "conversation_id": conversation_id,
            "user_id": owner_user_id,
            "chatbot_id": chatbot_id,
            "title": f"Visitor Chat - {user_message[:30]}",
            "summary": None,
            "summarized_message_count": 0,
            "summary_version": 0,
            "status": "active",
            "created_at": now,
            "updated_at": now
        }
        await conversations_col.insert_one(conv_doc)
        conv = conv_doc
    else:
        conversation_id = req_conv_id
        existing_conv = await conversations_col.find_one({"_id": conversation_id})
        if existing_conv:
            await conversations_col.update_one(
                {"_id": conversation_id},
                {"$set": {"updated_at": now}}
            )
            conv = existing_conv
        else:
            conv_doc = {
                "_id": conversation_id,
                "conversation_id": conversation_id,
                "user_id": owner_user_id,
                "chatbot_id": chatbot_id,
                "title": f"Visitor Chat - {user_message[:30]}",
                "summary": None,
                "summarized_message_count": 0,
                "summary_version": 0,
                "status": "active",
                "created_at": now,
                "updated_at": now
            }
            await conversations_col.insert_one(conv_doc)
            conv = conv_doc

    user_msg_id = str(uuid4())
    user_msg_doc = {
        "_id": user_msg_id,
        "conversation_id": conversation_id,
        "chatbot_id": chatbot_id,
        "user_id": owner_user_id,
        "role": "user",
        "content": user_message,
        "created_at": now
    }
    await messages_col.insert_one(user_msg_doc)

    history = await conversation_service.get_history(conversation_id)

    # Resolve system prompt: conversation > chatbot > prompt service default
    system_prompt = (conv and conv.get("system_prompt")) or (chatbot and chatbot.get("system_prompt"))
    if not system_prompt or not str(system_prompt).strip():
        system_prompt = f"You are {bot_name}, a helpful AI customer support agent."

    # Resolve LLM Config: chatbot llm_config_id > single user_llm_config document
    llm_config = None
    llm_config_id = chatbot.get("llm_config_id") if chatbot else None
    if llm_config_id:
        llm_config = await user_llm_config_service.get_raw_config(config_id=llm_config_id, user_id=owner_user_id)
    if not llm_config:
        llm_config = await user_llm_config_service.get_raw_user_config_by_user_id(user_id=owner_user_id)

    async def event_generator():
        yield f"data: {json.dumps({'type': 'conversation', 'conversation_id': conversation_id, 'chatbot_id': chatbot_id}, default=str)}\n\n"
        
        final_message = ""
        final_reasoning = None

        async for event in agent_service.astream_chat_response(
            messages=history,
            llm_config=llm_config,
            system_prompt=system_prompt
        ):
            if event.get("type") == "done":
                final_message = event.get("message", "")
                final_reasoning = event.get("reasoning_details")
            yield f"data: {json.dumps(event, default=str)}\n\n"

        # Store assistant message after stream completes
        assistant_msg_id = str(uuid4())
        assistant_msg_doc = {
            "_id": assistant_msg_id,
            "conversation_id": conversation_id,
            "chatbot_id": chatbot_id,
            "user_id": owner_user_id,
            "role": "assistant",
            "content": final_message,
            "reasoning_details": final_reasoning,
            "created_at": datetime.utcnow()
        }
        await messages_col.insert_one(assistant_msg_doc)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.delete(
    "/{chatbot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a chatbot by ID",
    description="Removes a chatbot from the system. The chatbot must belong to the authenticated user."
)
async def delete_chatbot(
    chatbot_id: str,
    current_user: dict = Depends(get_current_user),
    chatbot_service: ChatbotService = Depends(get_chatbot_service)
):
    user_id = current_user["id"]
    success = await chatbot_service.delete_chatbot(chatbot_id=chatbot_id, user_id=user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatbot not found, or you do not have permission to delete it."
        )
    return
