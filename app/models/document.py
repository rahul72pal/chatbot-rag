from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional

class DocumentModel(BaseModel):
    id: str
    user_id: str
    chatbot_id: str
    name: str
    size: str
    status: str = "indexed"
    chunks_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
