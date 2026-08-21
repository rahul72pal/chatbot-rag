from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List

class DocumentResponse(BaseModel):
    id: str
    user_id: str
    chatbot_id: str
    name: str
    size: str
    status: str
    chunks_count: int
    created_at: datetime

class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
