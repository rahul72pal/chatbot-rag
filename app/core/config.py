import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # DeepSeek / OpenRouter API Configuration
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    MODEL_NAME: str = "deepseek/deepseek-v4-flash-0731"
    OPEN_ROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # MongoDB Configuration
    MONGO_URL: str = ""
    DATABASE_NAME: str = "chatbot"

    # Qdrant Configuration
    QDRANT_URL: str = ""
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION_NAME: str = "chatbot_documents"

    # Embedding Configuration
    EMBEDDING_MODEL: str = "nvidia/nemotron-3-embed-1b:free"
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    # Application Settings
    APP_NAME: str = "FastAPI DeepSeek Chatbot"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # HTTP Client Configuration
    DEEPSEEK_TIMEOUT: float = 30.0
    DEEPSEEK_MAX_RETRIES: int = 3
    DEEPSEEK_RETRY_BACKOFF: float = 2.0

    #JWT SECREATS
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

# Global configuration instance
settings = Settings()

def get_settings() -> Settings:
    """Utility function to access settings instance."""
    return settings
