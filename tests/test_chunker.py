from app.core.chunker import extract_phrase, speech_chunks, split_sentences


def test_short_reply_is_one_request():
    assert speech_chunks("Your table for four is booked for seven.") == [
        "Your table for four is booked for seven."
    ]


def test_short_sentences_are_grouped_into_one_request():
    text = "Okay, it is done. Your table is ready."
    assert speech_chunks(text) == ["Okay, it is done. Your table is ready."]


def test_sentences_are_split_when_the_group_would_be_too_long():
    text = " ".join(["This is a complete sentence about reservations."] * 8)
    chunks = speech_chunks(text, max_chars=120)
    assert len(chunks) > 1
    assert all(len(chunk) <= 120 for chunk in chunks)
    assert all(chunk.endswith("reservations.") for chunk in chunks)


def test_long_sentence_breaks_on_clauses_not_words():
    text = (
        "We can seat your party of six in the garden area, provided the weather stays dry, "
        "and we will hold the table for fifteen minutes, so please arrive on time."
    )
    chunks = speech_chunks(text, max_chars=90)
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk[-1] in ",;:"


def test_split_sentences_keeps_punctuation():
    assert split_sentences("Hello there. How are you? Great!") == [
        "Hello there.",
        "How are you?",
        "Great!",
    ]


def test_extract_phrase_waits_for_sentence_end():
    phrase, rest = extract_phrase("Your table for")
    assert phrase == ""
    assert rest == "Your table for"


def test_extract_phrase_emits_a_complete_sentence():
    phrase, rest = extract_phrase("Your table is booked. Anything else")
    assert phrase == "Your table is booked."
    assert rest == "Anything else"


def test_one_word_opener_is_merged_with_the_next_sentence():
    phrase, rest = extract_phrase("Okay. Your table is booked for seven. Anything else")
    assert phrase == "Okay. Your table is booked for seven."
    assert rest == "Anything else"


def test_extract_phrase_releases_a_very_long_sentence_at_a_clause():
    text = (
        "We have a range of options available for you this evening, including the terrace, "
        "the private dining room and the main hall, all of which can be arranged for your party"
    )
    phrase, rest = extract_phrase(text)
    assert phrase.endswith(",")
    assert rest.startswith("including") or rest.startswith("the")
    assert phrase in text


def test_streaming_never_loses_or_repeats_words():
    text = (
        "Your table for four is booked for seven in the evening. "
        "We will hold it for fifteen minutes, so please arrive on time. "
        "Anything else I can help you with today?"
    )
    buffer = ""
    spoken: list[str] = []
    for token in text.split(" "):
        buffer += token + " "
        while True:
            phrase, buffer = extract_phrase(buffer)
            if not phrase:
                break
            spoken.append(phrase)
    if buffer.strip():
        spoken.append(buffer.strip())
    assert " ".join(spoken) == " ".join(text.split())


def test_streaming_releases_before_the_sentence_is_complete():
    buffer = (
        "Sure I can check that for you right now and the kitchen closes at eleven tonight "
        "so let me know"
    )
    phrase, rest = extract_phrase(buffer)
    assert phrase
    assert rest.strip()
    assert phrase in buffer


def test_unpunctuated_text_is_split_into_speakable_chunks():
    text = " ".join(["table"] * 40)
    chunks = speech_chunks(text)
    assert len(chunks) > 1
    assert " ".join(chunks) == text
