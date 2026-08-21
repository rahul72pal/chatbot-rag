from typing import List, Dict, Any, Optional
from datetime import datetime
from uuid import uuid4
from app.schemas.chatbot import ChatbotCreate, ChatbotUpdate

class ChatbotService:
    def __init__(self, mongo_db: Any) -> None:
        self._collection = mongo_db["chatbots"]

    async def create_chatbot(self, user_id: str, data: ChatbotCreate) -> Dict[str, Any]:
        """Creates a new chatbot for a user."""
        chatbot_doc = data.model_dump()
        chatbot_doc["_id"] = str(uuid4())
        chatbot_doc["user_id"] = user_id
        chatbot_doc["created_at"] = datetime.utcnow()
        chatbot_doc["updated_at"] = datetime.utcnow()

        await self._collection.insert_one(chatbot_doc)
        chatbot_doc["id"] = chatbot_doc.pop("_id")
        return chatbot_doc

    async def get_chatbot(self, chatbot_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a chatbot by ID. Accessible if public or owned by user."""
        doc = await self._collection.find_one({"_id": chatbot_id})
        if not doc:
            return None
        
        # Check permissions: must be public or owned by user
        if not doc.get("is_public") and doc.get("user_id") != user_id:
            return None
            
        doc["id"] = doc.pop("_id")
        return doc

    async def get_public_chatbot(self, chatbot_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves public details of a chatbot by ID without requiring user ownership."""
        doc = await self._collection.find_one({"_id": chatbot_id})
        if not doc:
            return None
        doc["id"] = doc.pop("_id")
        return doc


    async def get_user_chatbots(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves all chatbots belonging to a specific user."""
        cursor = self._collection.find({"user_id": user_id})
        chatbots = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            chatbots.append(doc)
        return chatbots

    async def update_chatbot(self, chatbot_id: str, user_id: str, data: ChatbotUpdate) -> Optional[Dict[str, Any]]:
        """Updates a chatbot if it belongs to the user."""
        # Find chatbot first to verify ownership
        doc = await self._collection.find_one({"_id": chatbot_id})
        if not doc or doc.get("user_id") != user_id:
            return None

        update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
        if not update_data:
            doc["id"] = doc.pop("_id")
            return doc

        update_data["updated_at"] = datetime.utcnow()

        await self._collection.update_one(
            {"_id": chatbot_id},
            {"$set": update_data}
        )

        # Get updated document
        updated_doc = await self._collection.find_one({"_id": chatbot_id})
        updated_doc["id"] = updated_doc.pop("_id")
        return updated_doc

    async def delete_chatbot(self, chatbot_id: str, user_id: str) -> bool:
        """Deletes a chatbot if it belongs to the user."""
        result = await self._collection.delete_one({"_id": chatbot_id, "user_id": user_id})
        return result.deleted_count > 0

    async def delete_user_chatbots(self, user_id: str) -> int:
        """Deletes all chatbots belonging to a user (used for cascade deletion)."""
        result = await self._collection.delete_many({"user_id": user_id})
        return result.deleted_count
