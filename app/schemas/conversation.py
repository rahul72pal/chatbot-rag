from typing import Optional, List, Any
from pydantic import BaseModel, Field
from datetime import datetime

class ConversationResponse(BaseModel):
    """API Response Schema for basic conversation metadata."""
    id: str = Field(..., description="The unique string/UUID of the conversation session.")
    user_id: str = Field(..., description="The owner user ID.")
    chatbot_id: str = Field(..., description="The associated chatbot ID.")
    title: Optional[str] = Field(default=None, description="The custom title of the conversation.")
    
    # Long-term compressed context
    summary: Optional[str] = Field(default=None, description="Long-term compressed context")

    # Number of messages already included in summary
    summarized_message_count: int = Field(default=0, description="Number of messages already included in summary")

    # Optional summary version
    summary_version: int = Field(default=0, description="Optional summary version")

    status: str = Field(default="active", description="The conversation status ('active', 'deleted').")
    created_at: datetime = Field(..., description="The creation date.")
    updated_at: datetime = Field(..., description="The update date.")


class MessageDetailResponse(BaseModel):
    """API Response Schema for message log details."""
    role: str = Field(..., description="The role of the message sender ('user', 'assistant', 'system').")
    content: str = Field(..., description="The text content of the message.")
    tokens: Optional[int] = Field(default=None, description="Token usage for this message.")
    created_at: datetime = Field(..., description="The creation date.")
    reasoning_details: Optional[Any] = Field(default=None, description="Optional reasoning details / chain-of-thought of the model.")


class ConversationDetailResponse(BaseModel):
    """API Response Schema for full conversation logs, including all messages."""
    conversation: ConversationResponse = Field(..., description="The conversation metadata details.")
    messages: List[MessageDetailResponse] = Field(..., description="The list of messages in this conversation.")
