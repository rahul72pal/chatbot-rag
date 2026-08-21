from typing import Optional, Literal
from pydantic import BaseModel, Field, model_validator
from datetime import datetime

class UserLLMConfigCreate(BaseModel):
    config_type: Literal["provider", "custom"] = Field(..., description="Type of configuration: 'provider' or 'custom'")
    
    # Provider-specific fields
    provider: Optional[str] = Field(default=None, description="Built-in provider name: 'openai', 'anthropic', or 'gemini'")
    default_model: Optional[str] = Field(default=None, description="Default model for built-in provider")
    
    # Custom endpoint fields
    name: Optional[str] = Field(default=None, description="Custom identifier name (e.g. 'OpenRouter')")
    base_url: Optional[str] = Field(default=None, description="Custom endpoint base URL")
    model: Optional[str] = Field(default=None, description="Custom endpoint model name")
    
    # Common fields
    api_key: str = Field(..., description="API key for the service")
    temperature: Optional[float] = Field(default=0.7, description="Generation temperature (0.0 to 2.0)")
    max_tokens: Optional[int] = Field(default=1000, description="Max token limit")

    # Qdrant Vector DB fields (Per-User DB Credentials)
    qdrant_url: Optional[str] = Field(default=None, description="Custom Qdrant server URL")
    qdrant_api_key: Optional[str] = Field(default=None, description="Custom Qdrant API key")
    qdrant_collection_name: Optional[str] = Field(default=None, description="Custom Qdrant collection name")

    @model_validator(mode="after")
    def validate_conditional_fields(self) -> "UserLLMConfigCreate":
        if self.config_type == "provider":
            if not self.provider:
                raise ValueError("provider must be specified when config_type is 'provider'")
            valid_providers = ["openai", "anthropic", "gemini"]
            if self.provider.lower() not in valid_providers:
                raise ValueError(f"provider must be one of {valid_providers}")
        elif self.config_type == "custom":
            if not self.name:
                raise ValueError("name must be specified when config_type is 'custom'")
            if not self.base_url:
                raise ValueError("base_url must be specified when config_type is 'custom'")
            if not self.model:
                raise ValueError("model must be specified when config_type is 'custom'")
        return self


class UserLLMConfigUpdate(BaseModel):
    config_type: Optional[str] = Field(default=None)
    provider: Optional[str] = Field(default=None)
    default_model: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    api_key: Optional[str] = Field(default=None)
    temperature: Optional[float] = Field(default=None)
    max_tokens: Optional[int] = Field(default=None)
    
    # Qdrant Vector DB fields
    qdrant_url: Optional[str] = Field(default=None)
    qdrant_api_key: Optional[str] = Field(default=None)
    qdrant_collection_name: Optional[str] = Field(default=None)


class UserLLMConfigResponse(BaseModel):
    id: str = Field(..., description="The unique configuration ID")
    user_id: str = Field(..., description="The owner user ID")
    config_type: Literal["provider", "custom"] = Field(..., description="Type of configuration")
    
    provider: Optional[str] = Field(default=None)
    default_model: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    api_key: str = Field(..., description="Masked or full API key")
    temperature: Optional[float] = Field(default=0.7)
    max_tokens: Optional[int] = Field(default=1000)

    # Qdrant Vector DB fields
    qdrant_url: Optional[str] = Field(default=None)
    qdrant_api_key: Optional[str] = Field(default=None)
    qdrant_collection_name: Optional[str] = Field(default=None)
    
    created_at: datetime = Field(..., description="The creation timestamp")
    updated_at: datetime = Field(..., description="The update timestamp")
