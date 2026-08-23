from typing import Any, Dict, List
from fastapi import APIRouter, Depends, status
from app.core.dependencies import get_current_user
from app.db.mongodb import db
from app.core.logger import logger

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get(
    "/overview",
    status_code=status.HTTP_200_OK,
    summary="Get aggregated user analytics and system usage limits",
    description="Returns total chatbots created, linked documents count, conversation count, message volume, token usage, and resource limits."
)
async def get_analytics_overview(
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Aggregates real-time usage stats and resource limits for authenticated user."""
    user_id = current_user["id"]
    database = db.database

    # 1. Chatbots count & list
    chatbots_cursor = database["chatbots"].find({"user_id": user_id})
    user_chatbots = []
    chatbot_ids = []
    async for cb in chatbots_cursor:
        cb_id = str(cb.get("_id"))
        chatbot_ids.append(cb_id)
        user_chatbots.append({
            "id": cb_id,
            "name": cb.get("name", "Untitled Chatbot"),
            "role": cb.get("role", "AI Assistant"),
            "is_public": cb.get("is_public", True),
            "doc_count": 0,
            "conversations_count": 0,
            "messages_count": 0
        })

    total_chatbots = len(user_chatbots)

    # 2. Document counts per chatbot
    docs_cursor = database["documents"].find({"user_id": user_id})
    doc_counts_map = {}
    total_documents = 0
    async for d in docs_cursor:
        total_documents += 1
        cb_id = d.get("chatbot_id")
        if cb_id:
            doc_counts_map[cb_id] = doc_counts_map.get(cb_id, 0) + 1

    # 3. Conversations count & stats
    # Match conversations by user_id OR owner_user_id OR linked chatbot_id
    conv_query: Dict[str, Any] = {
        "$or": [
            {"user_id": user_id},
            {"owner_user_id": user_id}
        ]
    }
    if chatbot_ids:
        conv_query["$or"].append({"chatbot_id": {"$in": chatbot_ids}})

    conv_cursor = database["conversations"].find(conv_query)
    conv_ids = []
    total_conversations = 0
    recent_activity = []
    async for conv in conv_cursor:
        total_conversations += 1
        conv_id = str(conv.get("_id"))
        conv_ids.append(conv_id)
        cb_id = conv.get("chatbot_id")
        
        # Increment chatbot conversation count
        for cb in user_chatbots:
            if cb["id"] == cb_id:
                cb["conversations_count"] += 1

        if len(recent_activity) < 5:
            recent_activity.append({
                "conversation_id": conv_id,
                "chatbot_id": cb_id,
                "created_at": str(conv.get("created_at")),
                "updated_at": str(conv.get("updated_at"))
            })

    # 4. Messages count & token usage
    total_messages = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0

    if conv_ids:
        # Correct MongoDB collection for messages is "messages"
        msg_cursor = database["messages"].find({"conversation_id": {"$in": conv_ids}})
        async for msg in msg_cursor:
            total_messages += 1
            
            # Check integer or dict tokens field
            tok = msg.get("tokens")
            if isinstance(tok, int):
                total_completion_tokens += tok
            elif isinstance(tok, dict):
                total_prompt_tokens += tok.get("prompt_tokens", 0)
                total_completion_tokens += tok.get("completion_tokens", 0)

            # Check usage dict field if present
            usage = msg.get("usage", {})
            if isinstance(usage, dict) and usage:
                total_prompt_tokens += usage.get("prompt_tokens", 0)
                total_completion_tokens += usage.get("completion_tokens", 0)

    total_tokens = total_prompt_tokens + total_completion_tokens

    # Attach document counts to chatbot details
    for cb in user_chatbots:
        cb["doc_count"] = doc_counts_map.get(cb["id"], 0)

    return {
        "user_id": user_id,
        "limits": {
            "max_chatbots": 5,
            "max_docs_per_chatbot": 2,
            "max_doc_size_mb": 2.0
        },
        "totals": {
            "chatbots": total_chatbots,
            "chatbots_limit": 5,
            "documents": total_documents,
            "conversations": total_conversations,
            "messages": total_messages,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens
        },
        "chatbots": user_chatbots,
        "recent_activity": recent_activity
    }
