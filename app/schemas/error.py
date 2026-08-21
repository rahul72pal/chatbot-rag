from typing import Any, Dict
from pydantic import BaseModel, Field

class ErrorResponse(BaseModel):
    """Uniform error response schema for API clients."""
    success: bool = Field(default=False, description="Indicates the status of the request (always False for errors).")
    error_code: str = Field(..., description="A unique programmatic error identifier.")
    message: str = Field(..., description="Human-readable description of the error.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional context or structural error details.")
