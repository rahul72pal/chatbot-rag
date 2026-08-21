from fastapi import APIRouter
from app.api import message, document, chatbot, conversation, user_llm_config

api_router = APIRouter()

# Register routes
api_router.include_router(message.router, tags=["Chatbot"])
api_router.include_router(document.router, tags=["Documents"])
api_router.include_router(chatbot.router, tags=["Chatbot Management"])
api_router.include_router(conversation.router, tags=["Conversations Management"])
api_router.include_router(user_llm_config.router, tags=["LLM Configurations"])
