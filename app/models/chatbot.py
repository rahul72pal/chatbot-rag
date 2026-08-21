from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

class Chatbot(BaseModel):
    """Domain model representing a custom chatbot."""
    id: UUID = Field(default_factory=uuid4)
    user_id: str  # References the User ID (string)
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    system_prompt: Optional[str] = None
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: int = 1000
    is_public: bool = True

    # Customization & Appearance
    theme_color: str = "#4f46e5"
    avatar_icon: str = "support"
    position: str = "right"
    bubble_style: str = "rounded"
    open_automatically: bool = False
    pop_after_seconds: int = 3
    show_welcome_tooltip: bool = False
    welcome_message: str = "Hi! How can I help you today?"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

