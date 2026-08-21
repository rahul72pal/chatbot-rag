from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from uuid import UUID
from app.core.dependencies import get_current_user, get_conversation_service
from app.services.conversation_service import ConversationService
from app.schemas.conversation import (
    ConversationResponse,
    ConversationDetailResponse,
    MessageDetailResponse
)

router = APIRouter(prefix="/conversation")

@router.get(
    "",
    response_model=List[ConversationResponse],
    status_code=status.HTTP_200_OK,
    summary="List active conversations",
    description="Returns a list of all active, non-deleted conversation sessions for the authenticated user."
)
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    conversation_service: ConversationService = Depends(get_conversation_service)
) -> List[ConversationResponse]:
    user_id = current_user["id"]
    conversations = await conversation_service.get_user_conversations(user_id=user_id)
    return [ConversationResponse(**conv) for conv in conversations]


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get conversation details",
    description="Retrieves metadata and full message history for a specific conversation session."
)
async def get_conversation_detail(
    conversation_id: UUID,
    current_user: dict = Depends(get_current_user),
    conversation_service: ConversationService = Depends(get_conversation_service)
) -> ConversationDetailResponse:
    user_id = current_user["id"]
    
    # 1. Fetch conversation metadata
    conv = await conversation_service.get_conversation(conversation_id=conversation_id, user_id=user_id)
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )
        
    # 2. Fetch messages history
    history = await conversation_service.get_history(conversation_id=conversation_id)
    
    # Map raw history to response model
    messages_detail = []
    for msg in history:
        messages_detail.append(
            MessageDetailResponse(
                role=msg["role"],
                content=msg["content"],
                tokens=msg.get("tokens"),
                created_at=msg["timestamp"],
                reasoning_details=msg.get("reasoning_details")
            )
        )
        
    return ConversationDetailResponse(
        conversation=ConversationResponse(**conv),
        messages=messages_detail
    )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete conversation",
    description="Soft-deletes a conversation session. The conversation and its messages will be permanently removed in 24 hours."
)
async def delete_conversation(
    conversation_id: UUID,
    current_user: dict = Depends(get_current_user),
    conversation_service: ConversationService = Depends(get_conversation_service)
):
    user_id = current_user["id"]
    success = await conversation_service.soft_delete_conversation(
        conversation_id=conversation_id,
        user_id=user_id
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or deletion failed."
        )
    return
