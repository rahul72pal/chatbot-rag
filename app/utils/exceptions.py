from typing import Any, Dict, Optional
from fastapi import status
from app.core.constants import (
    ERR_VALIDATION_FAILED,
    ERR_DEEPSEEK_API,
    ERR_DEEPSEEK_TIMEOUT,
    ERR_RATE_LIMIT_EXCEEDED,
    ERR_INTERNAL_SERVER,
    ERR_SERVICE_UNAVAILABLE,
)

class ChatbotException(Exception):
    """Base exception class for all chatbot-related domain exceptions."""
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: str = ERR_INTERNAL_SERVER,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}


class ValidationException(ChatbotException):
    """Exception raised when user input fails business rule validation (e.g., length, formatting)."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code=ERR_VALIDATION_FAILED,
            details=details,
        )


class RateLimitException(ChatbotException):
    """Exception raised when client requests exceed limits or upstream rate limit is hit (HTTP 429)."""
    def __init__(self, message: str = "Rate limit exceeded. Please try again later.", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error_code=ERR_RATE_LIMIT_EXCEEDED,
            details=details,
        )


class DeepSeekAPIException(ChatbotException):
    """Exception raised when the DeepSeek upstream API returns an error or invalid response."""
    def __init__(self, message: str, status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=status_code,
            error_code=ERR_DEEPSEEK_API,
            details=details,
        )


class DeepSeekTimeoutException(ChatbotException):
    """Exception raised when requests to the DeepSeek API time out."""
    def __init__(self, message: str = "Connection to DeepSeek API timed out.", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=ERR_DEEPSEEK_TIMEOUT,
            details=details,
        )


class InternalServerException(ChatbotException):
    """Exception raised for unhandled internal failures."""
    def __init__(self, message: str = "An unexpected error occurred.", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=ERR_INTERNAL_SERVER,
            details=details,
        )
