from datetime import datetime
from typing import List
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    """Domain model representing a single message in a chat history."""
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Conversation(BaseModel):
    """Domain model representing a full chat conversation session."""
    id: UUID = Field(default_factory=uuid4)
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
