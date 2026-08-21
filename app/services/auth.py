from bson import ObjectId

from app.db.mongodb import db
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
)


async def signup(
    name: str,
    email: str,
    password: str,
):

    existing_user = await db.users_collection.find_one({
        "email": email
    })

    if existing_user:
        raise ValueError("Email already registered")

    password_hash = hash_password(password)

    user = {
        "name": name,
        "email": email,
        "password_hash": password_hash,
    }

    result = await db.users_collection.insert_one(user)

    return {
        "id": str(result.inserted_id),
        "name": name,
        "email": email,
    }


async def login(
    email: str,
    password: str,
):

    user = await db.users_collection.find_one({
        "email": email
    })

    if not user:
        raise ValueError("Invalid email or password")

    is_valid = verify_password(
        password,
        user["password_hash"]
    )

    if not is_valid:
        raise ValueError("Invalid email or password")

    token = create_access_token(
        str(user["_id"])
    )

    return {
        "access_token": token,
        "token_type": "bearer",
    }


async def delete_user(user_id: str) -> bool:
    """Deletes a user and cascades deletion of all their chatbots, conversations, and messages."""
    from bson import ObjectId
    from app.services.chatbot_service import ChatbotService
    
    # 1. Delete all chatbots belonging to the user
    chatbot_service = ChatbotService(db.database)
    await chatbot_service.delete_user_chatbots(user_id)
    
    # 2. Cascade delete conversations and messages
    # Find all conversation IDs belonging to user
    cursor = db.conversations_collection.find({"user_id": user_id})
    async for conv in cursor:
        conv_id = conv["_id"]
        await db.messages_collection.delete_many({"conversation_id": conv_id})
    await db.conversations_collection.delete_many({"user_id": user_id})
    
    # 3. Cascade delete user LLM configurations
    from app.services.user_llm_config_service import UserLLMConfigService
    config_service = UserLLMConfigService(db.database)
    await config_service.delete_user_configs(user_id)
    
    # 4. Delete user document
    result = await db.users_collection.delete_one({"_id": ObjectId(user_id)})
    return result.deleted_count > 0