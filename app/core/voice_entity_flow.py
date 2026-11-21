"""Voice Agent Entity Extraction, Deterministic Normalization, Validation, and Confirmation Flow.

Implements the 6-step voice architecture:
1. Speech-to-Text (Groq Whisper) - Raw transcription
2. Entity Extraction (LLM / NLP) - Extract email, name, phone, date, reason
3. Deterministic Normalization (Python) - Convert spoken symbols into actual characters
4. Validation - Regex, format, length, and ambiguity checks
5. User Confirmation (Required) - Read back the complete normalized values verbally
6. Tool Execution - Save to database ONLY after user explicitly confirms
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.logger import logger

# Digit words mapping for spoken phone normalization
_DIGIT_WORDS: Dict[str, str] = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "plus": "+",
}

# Regex to detect spoken emails in transcripts
_SPOKEN_EMAIL_RE = re.compile(
    r"\b([a-z0-9._%+-]+(?:\s+(?:dot|underscore|dash|hyphen)\s+[a-z0-9._%+-]+)*)\s+at\s+([a-z0-9.-]+(?:\s+dot\s+[a-z0-9.-]+)*\s+dot\s+[a-z]{2,})\b",
    re.IGNORECASE,
)

# Regex to detect sequences of 4+ spoken digit words
_SPOKEN_PHONE_WORDS_RE = re.compile(
    r"\b(?:(?:plus|zero|oh|one|two|three|four|five|six|seven|eight|nine|\d+)\s+){3,}(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|\d+)\b",
    re.IGNORECASE,
)

# Standard RFC-compliant email regex
_EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


# ============================================================================
# Step 3: Deterministic Normalization (Python)
# ============================================================================

def normalize_spoken_email(text: str) -> str:
    """Convert spoken email tokens ('at' -> '@', 'dot' -> '.', etc.) into a clean email."""
    if not text or not text.strip():
        return ""

    text = text.lower().strip()
    replacements = {
        " at ": "@",
        " dot ": ".",
        " underscore ": "_",
        " dash ": "-",
        " hyphen ": "-",
    }
    text = f" {text} "
    for spoken, symbol in replacements.items():
        text = text.replace(spoken, symbol)

    # Strip internal spaces and surrounding punctuation
    text = re.sub(r"\s+", "", text)
    text = text.strip(" .,!?\"'")
    return text


def normalize_spoken_phone(text: str) -> str:
    """Convert spoken digit words (e.g. 'nine eight seven...') into clean numeric phone format."""
    if not text or not text.strip():
        return ""

    t = text.lower().strip()
    # Handle 'double X' and 'triple X'
    t = re.sub(r"\bdouble\s+(\w+)", r"\1 \1", t, flags=re.IGNORECASE)
    t = re.sub(r"\btriple\s+(\w+)", r"\1 \1 \1", t, flags=re.IGNORECASE)

    words = re.findall(r"\b(?:[a-z]+|[0-9]+|\+)\b", t)
    digits: List[str] = []
    has_plus = "+" in t or "plus" in words

    for w in words:
        if w in _DIGIT_WORDS:
            digits.append(_DIGIT_WORDS[w])
        elif w.isdigit():
            digits.append(w)

    res = "".join(digits)
    if has_plus and not res.startswith("+"):
        res = "+" + res.lstrip("+")
    return res


def normalize_name(text: str) -> str:
    """Normalize spoken name into clean Title Case without conversational filler prefixes."""
    if not text or not text.strip():
        return ""
    cleaned = re.sub(
        r"^(?:my\s+name\s+is|i\s+am|this\s+is|myself|it\s+is|name\s*:?)\s+",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^\w\s\'-]", "", cleaned).strip()
    return cleaned.title()


def normalize_time(text: str) -> str:
    """Normalize time and date phrasing."""
    if not text or not text.strip():
        return ""
    cleaned = text.strip().strip(" .,!?")
    # Capitalize standard am/pm
    cleaned = re.sub(r"\b([0-9]{1,2})\s*(?:am|a\.m\.)\b", r"\1:00 AM", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b([0-9]{1,2})\s*(?:pm|p\.m\.)\b", r"\1:00 PM", cleaned, flags=re.IGNORECASE)
    return cleaned


def normalize_transcript_symbols(text: str) -> str:
    """Pre-process raw STT transcripts to normalize both spoken emails and phone numbers."""
    if not text:
        return ""

    result = text

    # 1. Normalize spoken emails
    if " at " in result.lower():
        def _repl_email(m: re.Match) -> str:
            return normalize_spoken_email(m.group(0))
        result = _SPOKEN_EMAIL_RE.sub(_repl_email, result)

    # 2. Normalize spoken phone numbers
    def _repl_phone(m: re.Match) -> str:
        return normalize_spoken_phone(m.group(0))
    result = _SPOKEN_PHONE_WORDS_RE.sub(_repl_phone, result)

    return result


# ============================================================================
# Step 4: Validation (Regex, format and ambiguity checks)
# ============================================================================

def validate_email(email: str) -> Tuple[bool, str]:
    """Validate email format, checking for missing parts or ambiguous domains."""
    if not email:
        return False, "Email address is required."
    if "@" not in email:
        return False, "Email is missing the '@' symbol (e.g. name@domain.com)."

    parts = email.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False, "Invalid email address structure."

    domain = parts[1]
    if "." not in domain:
        return False, f"Email domain '{domain}' is missing an extension (like .com, .in, or .org)."

    ext = domain.split(".")[-1]
    if len(ext) < 2:
        return False, f"Email domain extension '.{ext}' is too short."

    if not _EMAIL_REGEX.match(email):
        return False, "Email contains invalid characters or formatting."

    return True, ""


def validate_phone(phone: str) -> Tuple[bool, str]:
    """Validate phone number format, ensuring 10-15 digits."""
    if not phone:
        return False, "Contact phone number is required."

    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return False, f"Phone number appears incomplete ({len(digits)} digits provided). Please provide a full 10-digit number."
    if len(digits) > 15:
        return False, f"Phone number has too many digits ({len(digits)} digits). Standard phone numbers are 10-15 digits."

    return True, ""


def validate_name(name: str) -> Tuple[bool, str]:
    """Validate person name."""
    if not name or len(name.strip()) < 2:
        return False, "Name is required and must be at least 2 characters."
    if re.search(r"\d", name):
        return False, "Name should not contain numbers."
    return True, ""


def validate_time(time_str: str) -> Tuple[bool, str]:
    """Validate preferred appointment time."""
    if not time_str or len(time_str.strip()) < 2:
        return False, "Preferred appointment date and time is required."
    return True, ""


def validate_reason(reason: str) -> Tuple[bool, str]:
    """Validate appointment reason/message."""
    if not reason or len(reason.strip()) < 2:
        return False, "Reason for appointment is required."
    return True, ""


def validate_all_entities(entities: Dict[str, str]) -> Tuple[bool, List[str], List[str]]:
    """Validate all entity slots.

    Returns:
        (is_valid, missing_fields, error_messages)
    """
    missing: List[str] = []
    errors: List[str] = []

    name = entities.get("name", "")
    email = entities.get("email", "")
    phone = entities.get("contact_number", "") or entities.get("phone", "")
    time_val = entities.get("time", "")
    reason = entities.get("reason", "")

    # Check presence
    if not name:
        missing.append("Name")
    else:
        v, err = validate_name(name)
        if not v:
            errors.append(err)

    if not email:
        missing.append("Email address")
    else:
        v, err = validate_email(email)
        if not v:
            errors.append(err)

    if not phone:
        missing.append("Contact phone number")
    else:
        v, err = validate_phone(phone)
        if not v:
            errors.append(err)

    if not time_val:
        missing.append("Preferred date and time")
    else:
        v, err = validate_time(time_val)
        if not v:
            errors.append(err)

    if not reason:
        missing.append("Reason for appointment")
    else:
        v, err = validate_reason(reason)
        if not v:
            errors.append(err)

    is_valid = len(missing) == 0 and len(errors) == 0
    return is_valid, missing, errors


# ============================================================================
# Step 5: User Confirmation (Required - Read back complete normalized value)
# ============================================================================

def format_readback_confirmation(entities: Dict[str, str]) -> str:
    """Format the complete normalized values for the voice agent to read back to the user."""
    name = entities.get("name", "N/A")
    email = entities.get("email", "N/A")
    phone = entities.get("contact_number", "") or entities.get("phone", "N/A")
    time_val = entities.get("time", "N/A")
    reason = entities.get("reason", "N/A")

    return (
        "I have noted your complete appointment details:\n"
        f"• Name: {name}\n"
        f"• Email: {email}\n"
        f"• Phone Number: {phone}\n"
        f"• Preferred Date & Time: {time_val}\n"
        f"• Reason: {reason}\n\n"
        "Do you confirm that you would like me to go ahead and book this appointment with these details?"
    )


# ============================================================================
# Voice Session Entity Tracker
# ============================================================================

@dataclass
class VoiceSessionEntityState:
    """Maintains entity slots and verification state across conversational turns in a voice call."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    time: Optional[str] = None
    reason: Optional[str] = None
    confirmed: bool = False
    readback_performed: bool = False

    def update_from_dict(self, data: Dict[str, Any]) -> None:
        """Merge incoming raw entities, normalizing them deterministically."""
        if data.get("name"):
            self.name = normalize_name(str(data["name"]))
        if data.get("email"):
            self.email = normalize_spoken_email(str(data["email"]))
        if data.get("contact_number") or data.get("phone"):
            raw_phone = str(data.get("contact_number") or data.get("phone"))
            self.phone = normalize_spoken_phone(raw_phone)
        if data.get("time"):
            self.time = normalize_time(str(data["time"]))
        if data.get("reason"):
            self.reason = str(data["reason"]).strip()
        if data.get("confirmed") is not None:
            self.confirmed = bool(data["confirmed"])

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name or "",
            "email": self.email or "",
            "contact_number": self.phone or "",
            "phone": self.phone or "",
            "time": self.time or "",
            "reason": self.reason or "",
        }

    def validate(self) -> Tuple[bool, List[str], List[str]]:
        return validate_all_entities(self.to_dict())


# ============================================================================
# Step 7: Pipecat Voice Flow Integration
# ============================================================================

def create_pipecat_voice_agent(
    transport: Optional[Any] = None,
    runner_args: Any = None,
    custom_llm: Optional[Any] = None,
    user_config: Optional[Dict[str, Any]] = None,
    system_instruction: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Factory helper to instantiate a PipecatVoiceAgent configured with deterministic entity flow."""
    from app.core.pipecat_voice_agent import PipecatVoiceAgent
    return PipecatVoiceAgent(
        transport=transport,
        runner_args=runner_args,
        custom_llm=custom_llm,
        user_config=user_config,
        system_instruction=system_instruction,
        **kwargs,
    )


