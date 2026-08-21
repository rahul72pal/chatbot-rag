from typing import Any, Optional, Dict, List
from fastapi import Depends, Request
import httpx
from app.core.config import settings, Settings
from app.services.prompt_service import PromptService
from app.services.conversation_service import ConversationService
from app.services.agent_service import AgentService
from app.services.deepseek_service import DeepSeekService
from app.services.embedding_service import NvidiaEmbeddingService
from app.services.qdrant_service import QdrantService
from app.services.document_service import DocumentService

# Singletons initialized once
prompt_service = PromptService()


def get_settings() -> Settings:
    """Dependency provider for global settings."""
    return settings


def get_prompt_service() -> PromptService:
    """Dependency provider for PromptService."""
    return prompt_service


def get_conversation_service(
    request: Request,
    prompt_service: PromptService = Depends(get_prompt_service)
) -> ConversationService:
    """Dependency provider for ConversationService."""
    mongo_db = request.app.state.mongo_db
    return ConversationService(prompt_service=prompt_service, mongo_db=mongo_db)


async def get_agent_service(
    request: Request,
    settings: Settings = Depends(get_settings)
) -> AgentService:
    """Dependency provider for AgentService, sharing the app's HTTP client."""
    client = request.app.state.http_client
    return AgentService(client=client, settings=settings)


async def get_deepseek_service(
    request: Request,
    settings: Settings = Depends(get_settings)
) -> AgentService:
    """Dependency provider for DeepSeekService (alias for AgentService)."""
    return await get_agent_service(request=request, settings=settings)


def get_embedding_service() -> NvidiaEmbeddingService:
    """Dependency provider for NvidiaEmbeddingService."""
    return NvidiaEmbeddingService()


def get_qdrant_service(
    request: Request,
    embedding_service: NvidiaEmbeddingService = Depends(get_embedding_service)
) -> QdrantService:
    """Dependency provider for QdrantService, injecting the embedding client and mongo_db."""
    mongo_db = request.app.state.mongo_db
    return QdrantService(embeddings=embedding_service, mongo_db=mongo_db)


def get_document_service(
    request: Request,
    qdrant_service: QdrantService = Depends(get_qdrant_service)
) -> DocumentService:
    """Dependency provider for DocumentService."""
    mongo_db = request.app.state.mongo_db
    return DocumentService(qdrant_service=qdrant_service, mongo_db=mongo_db)



def get_chatbot_service(request: Request) -> Any:
    """Dependency provider for ChatbotService."""
    from app.services.chatbot_service import ChatbotService
    mongo_db = request.app.state.mongo_db
    return ChatbotService(mongo_db=mongo_db)


def get_user_llm_config_service(request: Request) -> Any:
    """Dependency provider for UserLLMConfigService."""
    from app.services.user_llm_config_service import UserLLMConfigService
    mongo_db = request.app.state.mongo_db
    return UserLLMConfigService(mongo_db=mongo_db)


from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security_scheme = HTTPBearer()

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme)
) -> dict:
    """Dependency provider to authenticate and retrieve the current user."""
    from app.db.mongodb import db
    from bson import ObjectId
    
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID."
            )
    except jwt.PyJWTError:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials."
        )
        
    try:
        user = await db.users_collection.find_one({"_id": ObjectId(user_id)})
    except Exception:
        user = None
        
    if not user:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found."
        )
        
    user["id"] = str(user["_id"])
    return user


security_scheme_optional = HTTPBearer(auto_error=False)

async def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme_optional)
) -> Optional[dict]:
    """Dependency provider to optionally retrieve the current user without raising 401 if unauthenticated."""
    if not credentials or not credentials.credentials:
        return None
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            return None
        from app.db.mongodb import db
        from bson import ObjectId
        user = await db.users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            user["id"] = str(user["_id"])
            return user
    except Exception:
        pass
    return None
