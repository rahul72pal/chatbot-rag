import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
            ".env",
        ),
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

    # Voice pipeline providers. Speech models come from the environment;
    # the conversational LLM model comes from each user's LLM configuration.
    GROQ_API_KEY: str = ""
    STT_MODEL: str = "whisper-large-v3-turbo"
    STT_PROVIDER: str = "deepgram"        # deepgram | groq
    DEEPGRAM_STT_MODEL: str = "nova-3"
    GEMINI_API_KEY: str = ""
    TTS_MODEL: str = "gemini-2.5-flash-preview-tts"
    TTS_VOICE: str = "Kore"
    GOOGLE_APPLICATION_CREDENTIALS: str = "./google-credentials.json"
    TTS_PROVIDER: str = "fish"            # fish | deepgram
    DEEPGRAM_API: str = ""
    FISH_AUDIO_API_KEY: str = ""
    FISH_AUDIO_MODEL: str = "s2.1-pro-free"
    FISH_AUDIO_REFERENCE_ID: str = "ca3007f96ae7499ab87d27ea3599956a"
    VOICE_MAX_HISTORY_TURNS: int = 10
    DATABASE_URL: str = "sqlite+aiosqlite:///./voice_agent.db"

    # Public voice agent. The agent is anonymous, so the backend owns the
    # conversational model and the caller never supplies an API key.
    PUBLIC_LLM_API_KEY: str = ""
    PUBLIC_LLM_MODEL: str = ""
    PUBLIC_LLM_BASE_URL: str = ""
    PUBLIC_SESSION_TTL_HOURS: int = 24
    PUBLIC_SESSION_MAX_PER_IP_PER_HOUR: int = 30

    # Tool execution budget (Phase 5)
    TOOL_TIMEOUT_S: float = 8.0
    MAX_TOOL_ITERATIONS: int = 5
    TIMEZONE: str = "Asia/Kolkata"
    CORS_ALLOWED_ORIGINS: str = "*"

    # Application Settings
    APP_NAME: str = "FastAPI DeepSeek Chatbot"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    PORT: int = int(os.environ.get("PORT", "8000"))
    HOST: str = "0.0.0.0"

    @property
    def server_port(self) -> int:
        port_env = os.environ.get("PORT")
        if port_env and port_env.isdigit():
            return int(port_env)
        return self.PORT

    @property
    def allowed_origins(self) -> list[str]:
        """Read browser origins from a comma-separated environment setting."""
        if not self.CORS_ALLOWED_ORIGINS or self.CORS_ALLOWED_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

    def public_llm_config(self) -> dict[str, str] | None:
        """Resolve the backend LLM configuration used by anonymous visitors."""
        model = self.PUBLIC_LLM_MODEL or self.MODEL_NAME
        if self.PUBLIC_LLM_API_KEY and model:
            if self.PUBLIC_LLM_BASE_URL:
                return {
                    "config_type": "custom",
                    "base_url": self.PUBLIC_LLM_BASE_URL,
                    "model": model,
                    "api_key": self.PUBLIC_LLM_API_KEY,
                }
            return {
                "config_type": "provider",
                "provider": "openai",
                "default_model": model,
                "api_key": self.PUBLIC_LLM_API_KEY,
            }
        if self.OPEN_ROUTER_API_KEY:
            return {
                "config_type": "provider",
                "provider": "openrouter",
                "default_model": model,
                "api_key": self.OPEN_ROUTER_API_KEY,
            }
        if self.DEEPSEEK_API_KEY:
            return {
                "config_type": "custom",
                "base_url": self.DEEPSEEK_BASE_URL,
                "model": model,
                "api_key": self.DEEPSEEK_API_KEY,
            }
        if self.GEMINI_API_KEY:
            return {
                "config_type": "provider",
                "provider": "gemini",
                "default_model": "gemini-2.5-flash",
                "api_key": self.GEMINI_API_KEY,
            }
        return None

    # HTTP Client Configuration
    DEEPSEEK_TIMEOUT: float = 30.0
    DEEPSEEK_MAX_RETRIES: int = 3
    DEEPSEEK_RETRY_BACKOFF: float = 2.0

    #JWT SECREATS
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

# Global configuration instance
settings = Settings()

def get_settings() -> Settings:
    """Utility function to access settings instance."""
    return settings
