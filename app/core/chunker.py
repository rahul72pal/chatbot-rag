"""Sentence-aware speech chunking for natural-sounding TTS.

Gemini TTS regenerates prosody from scratch for every request, so cutting text
every few words leaves audible seams and a robotic rhythm. Speech is therefore
split on sentence boundaries, and only genuinely long sentences are broken
further - at clause boundaries (commas, semicolons, dashes) or, as a last
resort, at a word boundary. Short replies stay a single request, so the first
audio arrives as fast as possible.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

SENTENCE_END = re.compile(r"(?<=[.!?\u0964\u2026])\s+|\n+")
SENTENCE_MARK = re.compile(r"[.!?\u0964\u2026]+[\"'\u201d\u2019)\]]*\s")
CLAUSE_MARK = re.compile(r"[,;:\u2014\u2013]\s")

MIN_SENTENCE_WORDS = 2
# Past these limits a single sentence is too long to wait for: speak the first
# natural clause group instead of the whole sentence.
LONG_SENTENCE_WORDS = 18
LONG_SENTENCE_CHARS = 200


def split_sentences(text: str) -> list[str]:
    """Split text into complete sentences, keeping their punctuation."""
    return [sentence.strip() for sentence in SENTENCE_END.split(text) if sentence.strip()]


def _split_long(sentence: str, limit: int = LONG_SENTENCE_CHARS) -> list[str]:
    """Break one oversized sentence at clause boundaries, then at words."""
    pieces: list[str] = []
    remaining = sentence.strip()
    while len(remaining) > limit:
        window = remaining[:limit]
        clause = next(
            (m for m in CLAUSE_MARK.finditer(window) if m.end() >= limit // 3), None
        )
        if clause is not None:
            cut = clause.end()
        else:
            space = window.rfind(" ")
            if space <= 0:
                break
            cut = space + 1
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def speech_chunks(text: str, max_chars: int = LONG_SENTENCE_CHARS) -> list[str]:
    """Group whole sentences into natural TTS requests of at most ``max_chars``."""
    chunks: list[str] = []
    for sentence in split_sentences(text):
        for piece in _split_long(sentence, max_chars):
            if chunks and len(chunks[-1]) + 1 + len(piece) <= max_chars:
                chunks[-1] = f"{chunks[-1]} {piece}"
            else:
                chunks.append(piece)
    return chunks


def extract_phrase(buffer: str, is_first: bool = False) -> tuple[str, str]:
    """Return the next speakable phrase from a growing LLM token buffer.

    Emits complete sentences. For the very first chunk of a turn, natural
    clauses (comma, colon, dash) after 3+ words or short greetings ("Sure!", "Hello!")
    are released immediately so the user hears speech with minimal latency.
    """
    text = buffer
    stripped = text.lstrip()
    if not stripped:
        return "", text

    sentence = SENTENCE_MARK.search(text)
    if sentence is not None:
        prefix = text[: sentence.end()]
        word_count = len(prefix.split())
        # Single exclamation/greeting like "Hello!" or "Sure!" can be emitted early
        if word_count >= 1 and any(p in prefix for p in ("!", "?", "।")):
            return prefix.strip(), text[sentence.end():]
        if word_count >= MIN_SENTENCE_WORDS:
            return prefix.strip(), text[sentence.end():]
        following = SENTENCE_MARK.search(text, sentence.end())
        if following is not None:
            return text[: following.end()].strip(), text[following.end():]

    words = stripped.split()
    # Fast first-clause emission for ultra-low latency voice response:
    # If the first chunk contains a clause mark (comma, dash, colon) with 2+ words,
    # or a common single-word conversational anchor ("Sure,", "Certainly,", "Okay,", "Got it,"),
    # emit immediately so TTS synthesis starts without waiting for the full sentence.
    if is_first:
        clause = CLAUSE_MARK.search(stripped)
        if clause is not None:
            prefix = stripped[: clause.end()]
            remainder = stripped[clause.end():]
            prefix_words = prefix.split()
            is_anchor = len(prefix_words) == 1 and prefix_words[0].rstrip(",;:-!").lower() in {
                "sure", "certainly", "absolutely", "alright", "okay", "yes", "hello", "hi", "right"
            }
            if (len(prefix_words) >= 2 or is_anchor) and len(remainder.split()) >= 1:
                cut = clause.end()
                return stripped[:cut].strip(), stripped[cut:]

    too_long = len(words) > LONG_SENTENCE_WORDS or len(stripped) > LONG_SENTENCE_CHARS
    if not too_long:
        return "", buffer

    window = stripped[:LONG_SENTENCE_CHARS]
    min_cut = min(LONG_SENTENCE_CHARS, len(window)) // 3
    clause = next(
        (m for m in CLAUSE_MARK.finditer(window) if m.end() >= min_cut), None
    )
    if clause is not None:
        cut = clause.end()
    else:
        space = window.rfind(" ")
        if space <= 0:
            return "", buffer
        cut = space + 1
    return stripped[:cut].strip(), stripped[cut:]


async def sentences_from_stream(token_stream: AsyncIterator[str]) -> AsyncIterator[str]:
    buffer = ""
    async for token in token_stream:
        buffer += token
        phrase, buffer = extract_phrase(buffer)
        while phrase:
            yield phrase
            phrase, buffer = extract_phrase(buffer)
    if buffer.strip():
        yield buffer.strip()
