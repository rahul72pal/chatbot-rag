"""Spoken email normalization utility for voice agent sessions.

Converts verbally spoken email addresses (e.g. 'john dot doe at gmail dot com')
into standard email formats ('john.doe@gmail.com') without relying purely on LLM formatting.
"""

from __future__ import annotations

import re

# Pattern matching verbal email expressions in conversational sentences
_SPOKEN_EMAIL_RE = re.compile(
    r"\b([a-z0-9._%+-]+(?:\s+(?:dot|underscore|dash|hyphen)\s+[a-z0-9._%+-]+)*)\s+at\s+([a-z0-9.-]+(?:\s+dot\s+[a-z0-9.-]+)*\s+dot\s+[a-z]{2,})\b",
    re.IGNORECASE,
)


def normalize_spoken_email(text: str) -> str:
    """Normalize a spoken email string into standard email format.

    Replaces spoken tokens:
    - ' at ' -> '@'
    - ' dot ' -> '.'
    - ' underscore ' -> '_'
    - ' dash ' / ' hyphen ' -> '-'
    And removes internal spaces.
    """
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

    text = re.sub(r"\s+", "", text)
    text = text.strip(" .,!?")

    return text


def normalize_transcript_emails(text: str) -> str:
    """Detect and replace spoken emails within full conversational user transcripts.

    Example:
    'My email is john dot doe at gmail dot com and call me tomorrow'
    -> 'My email is john.doe@gmail.com and call me tomorrow'
    """
    if not text or " at " not in text.lower():
        return text

    def _replace_match(match: re.Match) -> str:
        return normalize_spoken_email(match.group(0))

    return _SPOKEN_EMAIL_RE.sub(_replace_match, text)

