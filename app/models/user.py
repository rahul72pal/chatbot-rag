from typing import List, Optional
from datetime import datetime
from datetime import datetime
from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from pydantic import EmailStr

class User(BaseModel):
    """Domain model representing a user in the system"""
    email: EmailStr
    name: str
    hashed_password: str
    role: str 
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
