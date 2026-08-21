from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ChatbotCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    avatar_url: Optional[str] = Field(None, max_length=500)
    system_prompt: Optional[str] = None
    model: str = Field("gpt-3.5-turbo", max_length=50)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(1000, gt=0)
    is_public: bool = True
    theme_color: Optional[str] = Field("#4f46e5", max_length=50)
    avatar_icon: Optional[str] = Field("support", max_length=50)
    position: Optional[str] = Field("right", max_length=20)
    bubble_style: Optional[str] = Field("rounded", max_length=20)
    open_automatically: Optional[bool] = False
    pop_after_seconds: Optional[int] = 3
    show_welcome_tooltip: Optional[bool] = False
    welcome_message: Optional[str] = Field("Hi! How can I help you today?", max_length=1000)

class ChatbotUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    avatar_url: Optional[str] = Field(None, max_length=500)
    system_prompt: Optional[str] = None
    model: Optional[str] = Field(None, max_length=50)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=0)
    is_public: Optional[bool] = None
    theme_color: Optional[str] = Field(None, max_length=50)
    avatar_icon: Optional[str] = Field(None, max_length=50)
    position: Optional[str] = Field(None, max_length=20)
    bubble_style: Optional[str] = Field(None, max_length=20)
    open_automatically: Optional[bool] = None
    pop_after_seconds: Optional[int] = None
    show_welcome_tooltip: Optional[bool] = None
    welcome_message: Optional[str] = Field(None, max_length=1000)

class ChatbotResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    system_prompt: Optional[str] = None
    model: str
    temperature: float
    max_tokens: int
    is_public: bool
    theme_color: Optional[str] = "#4f46e5"
    avatar_icon: Optional[str] = "support"
    position: Optional[str] = "right"
    bubble_style: Optional[str] = "rounded"
    open_automatically: Optional[bool] = False
    pop_after_seconds: Optional[int] = 3
    show_welcome_tooltip: Optional[bool] = False
    welcome_message: Optional[str] = "Hi! How can I help you today?"
    created_at: datetime
    updated_at: Optional[datetime] = None

