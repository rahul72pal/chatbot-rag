from app.core.constants import MAX_MESSAGE_LENGTH
from app.utils.exceptions import ValidationException

def validate_chat_message(message: str) -> str:
    """Validates the input message.
    
    Raises:
        ValidationException: If message is empty, whitespace-only, or too long.
    """
    if message is None:
        raise ValidationException("Message cannot be null.")
        
    if not isinstance(message, str):
        raise ValidationException("Message must be a string.")
        
    stripped = message.strip()
    if not stripped:
        raise ValidationException("Message cannot be empty or consist only of whitespace.")
        
    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValidationException(
            f"Message length ({len(message)}) exceeds the maximum allowed limit of {MAX_MESSAGE_LENGTH} characters."
        )
        
    return message
