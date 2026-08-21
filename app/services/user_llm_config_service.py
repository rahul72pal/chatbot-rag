from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import uuid4
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.schemas.user_llm_config import UserLLMConfigCreate, UserLLMConfigUpdate

def mask_api_key(api_key: str) -> str:
    """Masks sensitive API keys for safe JSON output."""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "••••" + api_key[-2:] if len(api_key) > 2 else "••••"
    return api_key[:4] + "..." + api_key[-4:]

class UserLLMConfigService:
    def __init__(self, mongo_db: AsyncIOMotorDatabase):
        self._collection = mongo_db["user_llm_configs"]

    async def create_config(self, user_id: str, payload: UserLLMConfigCreate) -> Dict[str, Any]:
        """Creates or updates (upserts) a single LLM API configuration for the specified user."""
        now = datetime.utcnow()
        config_doc = payload.model_dump()
        
        # Enforce single configuration document per user
        existing = await self._collection.find_one({"user_id": user_id})
        if existing:
            config_id = existing["_id"]
            # If incoming API key is masked, preserve existing raw key
            if "api_key" in config_doc and config_doc["api_key"]:
                if any(char in config_doc["api_key"] for char in ["•", "*", "..."]):
                    config_doc.pop("api_key", None)
            
            config_doc["updated_at"] = now
            await self._collection.update_one(
                {"_id": config_id, "user_id": user_id},
                {"$set": config_doc}
            )
            updated_doc = await self._collection.find_one({"_id": config_id, "user_id": user_id})
            updated_doc["id"] = updated_doc.pop("_id")
            updated_doc["api_key"] = mask_api_key(updated_doc["api_key"])
            return updated_doc
        else:
            config_doc["_id"] = str(uuid4())
            config_doc["user_id"] = user_id
            config_doc["created_at"] = now
            config_doc["updated_at"] = now
            
            await self._collection.insert_one(config_doc)
            config_doc["id"] = config_doc.pop("_id")
            config_doc["api_key"] = mask_api_key(config_doc["api_key"])
            return config_doc

    async def get_user_configs(self, user_id: str) -> List[Dict[str, Any]]:
        """Lists all LLM configurations for the user, with masked API keys."""
        cursor = self._collection.find({"user_id": user_id})
        configs = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            doc["api_key"] = mask_api_key(doc["api_key"])
            configs.append(doc)
        return configs

    async def get_config(self, config_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a specific LLM configuration with masked API key."""
        doc = await self._collection.find_one({"_id": config_id, "user_id": user_id})
        if not doc:
            return None
        doc["id"] = doc.pop("_id")
        doc["api_key"] = mask_api_key(doc["api_key"])
        return doc

    async def get_raw_config(self, config_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a configuration with the actual unmasked API key (for service backend use)."""
        doc = await self._collection.find_one({"_id": config_id, "user_id": user_id})
        if not doc:
            return None
        doc["id"] = doc.pop("_id")
        return doc

    async def get_raw_user_config_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves the single unmasked LLM configuration for a user."""
        doc = await self._collection.find_one({"user_id": user_id})
        if not doc:
            return None
        doc["id"] = doc.pop("_id")
        return doc

    async def update_config(self, config_id: str, user_id: str, payload: UserLLMConfigUpdate) -> Optional[Dict[str, Any]]:
        """Updates a configuration. Does not overwrite API key if incoming key is masked."""
        existing = await self._collection.find_one({"_id": config_id, "user_id": user_id})
        if not existing:
            return None
            
        update_data = payload.model_dump(exclude_unset=True)
        
        # If API key is provided and masked, do not overwrite the raw key
        if "api_key" in update_data and update_data["api_key"]:
            incoming_key = update_data["api_key"]
            if any(char in incoming_key for char in ["•", "*", "..."]):
                update_data.pop("api_key")
                
        if update_data:
            update_data["updated_at"] = datetime.utcnow()
            await self._collection.update_one(
                {"_id": config_id, "user_id": user_id},
                {"$set": update_data}
            )
            
        return await self.get_config(config_id, user_id)

    async def delete_config(self, config_id: str, user_id: str) -> bool:
        """Deletes a configuration."""
        result = await self._collection.delete_one({"_id": config_id, "user_id": user_id})
        return result.deleted_count > 0

    async def delete_user_configs(self, user_id: str) -> None:
        """Cascade deletes all configurations belonging to the user."""
        await self._collection.delete_many({"user_id": user_id})
