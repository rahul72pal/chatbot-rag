from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator
from app.utils.validators import validate_chat_message

class MessageRequest(BaseModel):
    """API Request Schema for sending a message to the chatbot."""
    conversation_id: Optional[UUID] = Field(
        default=None,
        description="Optional conversation ID. If not provided, a new one is automatically generated."
    )
    chatbot_id: Optional[str] = Field(
        default=None,
        description="Optional chatbot ID. Required if starting a new conversation session."
    )
    message: str = Field(
        ...,
        description="The message text from the user. Cannot be empty, whitespace-only, or exceed 5000 characters."
    )

    @field_validator("message")
    @classmethod
    def validate_message_field(cls, value: str) -> str:
        """Validates that the message meets size and content constraints."""
        # Use our domain validator which throws custom ValidationException (HTTP 400)
        return validate_chat_message(value)
