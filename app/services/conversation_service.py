from uuid import UUID, uuid4
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.core.logger import logger
from app.services.prompt_service import PromptService

class ConversationService:
    """Manages chat history, sessions, and messages in MongoDB using normalized collections."""
    
    def __init__(self, prompt_service: PromptService, mongo_db: Any) -> None:
        self._prompt_service = prompt_service
        self._conversations = mongo_db["conversations"]
        self._messages = mongo_db["messages"]

    async def create_conversation(self, user_id: str, chatbot_id: str, title: Optional[str] = None) -> UUID:
        """Generates a new conversation session, metadata, and saves to MongoDB."""
        conv_id = uuid4()
        now = datetime.utcnow()
        
        conversation_doc = {
            "_id": str(conv_id),
            "user_id": user_id,
            "chatbot_id": chatbot_id,
            "title": title or "New Conversation",
            "summary": None,
            "summarized_message_count": 0,
            "summary_version": 0,
            "status": "active",
            "deleted": None,
            "created_at": now,
            "updated_at": now
        }
        
        await self._conversations.insert_one(conversation_doc)
        logger.info(f"Initialized new normalized conversation: {conv_id} for user {user_id} and chatbot {chatbot_id}")
        return conv_id

    async def get_conversation(self, conversation_id: UUID | str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves an active conversation's metadata by ID."""
        conv_str = str(conversation_id)
        query: Dict[str, Any] = {"_id": conv_str, "status": {"$ne": "deleted"}}
        if user_id:
            query["user_id"] = user_id

        doc = await self._conversations.find_one(query)
        if not doc:
            return None
        
        doc["id"] = doc.pop("_id")
        return doc

    async def get_user_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves list of active conversation sessions owned by the authenticated user."""
        cursor = self._conversations.find({
            "user_id": user_id,
            "status": {"$ne": "deleted"}
        }).sort("updated_at", -1)
        
        conversations = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            conversations.append(doc)
        return conversations

    async def get_history(self, conversation_id: UUID | str) -> List[Dict[str, Any]]:
        """Retrieves full message logs for a conversation session, sorted by creation time."""
        conv_str = str(conversation_id)
        cursor = self._messages.find({
            "conversation_id": conv_str,
            "deleted": None
        }).sort("created_at", 1)
        
        history = []
        async for doc in cursor:
            msg = {
                "role": doc["role"],
                "content": doc["content"],
                "tokens": doc.get("tokens"),
                "timestamp": doc["created_at"].isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at")
            }
            if "reasoning_details" in doc and doc["reasoning_details"] is not None:
                msg["reasoning_details"] = doc["reasoning_details"]
            history.append(msg)
            
        return history

    async def add_message(
        self,
        conversation_id: UUID | str,
        role: str,
        content: str,
        tokens: Optional[int] = None,
        reasoning_details: Any = None
    ) -> None:
        """Appends a new message document to the messages collection and updates conversation timestamp."""
        conv_str = str(conversation_id)
        now = datetime.utcnow()
        
        message_doc = {
            "_id": str(uuid4()),
            "conversation_id": conv_str,
            "role": role,
            "content": content,
            "tokens": tokens,
            "created_at": now,
            "deleted": None
        }
        if reasoning_details is not None:
            message_doc["reasoning_details"] = reasoning_details
            
        await self._messages.insert_one(message_doc)
        
        # Update conversations collection timestamp
        await self._conversations.update_one(
            {"_id": conv_str},
            {"$set": {"updated_at": now}}
        )
        logger.info(f"Added message from '{role}' to conversation {conversation_id} in messages collection")

    async def soft_delete_conversation(self, conversation_id: UUID | str, user_id: str) -> bool:
        """Flags a conversation and its messages as deleted, scheduling them for 24h TTL cleanup."""
        conv_str = str(conversation_id)
        now = datetime.utcnow()
        
        conv = await self._conversations.find_one({
            "_id": conv_str,
            "user_id": user_id,
            "status": {"$ne": "deleted"}
        })
        if not conv:
            return False
            
        await self._conversations.update_one(
            {"_id": conv_str},
            {"$set": {
                "status": "deleted",
                "deleted": now,
                "updated_at": now
            }}
        )
        
        await self._messages.update_many(
            {"conversation_id": conv_str},
            {"$set": {"deleted": now}}
        )
        
        logger.info(f"Soft-deleted conversation {conversation_id} and its messages for user {user_id}")
        return True
