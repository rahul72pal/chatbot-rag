from typing import Final

# Chat message limits
MIN_MESSAGE_LENGTH: Final[int] = 1
MAX_MESSAGE_LENGTH: Final[int] = 5000

# Chat roles
ROLE_SYSTEM: Final[str] = "system"
ROLE_USER: Final[str] = "user"
ROLE_ASSISTANT: Final[str] = "assistant"

# API Route prefixes and routes
API_VERSION: Final[str] = "/api/v1"
ROUTE_MESSAGE: Final[str] = "/message"

# HTTP Headers
HEADER_AUTHORIZATION: Final[str] = "Authorization"
HEADER_CONTENT_TYPE: Final[str] = "Content-Type"
HEADER_X_REQUEST_ID: Final[str] = "X-Request-ID"
JSON_CONTENT_TYPE: Final[str] = "application/json"

# Error Codes
ERR_VALIDATION_FAILED: Final[str] = "VALIDATION_FAILED"
ERR_DEEPSEEK_API: Final[str] = "DEEPSEEK_API_ERROR"
ERR_DEEPSEEK_TIMEOUT: Final[str] = "DEEPSEEK_TIMEOUT_ERROR"
ERR_RATE_LIMIT_EXCEEDED: Final[str] = "RATE_LIMIT_EXCEEDED"
ERR_INTERNAL_SERVER: Final[str] = "INTERNAL_SERVER_ERROR"
ERR_SERVICE_UNAVAILABLE: Final[str] = "SERVICE_UNAVAILABLE"
