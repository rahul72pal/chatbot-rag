"""Echo-gate behaviour: speaker bleed must not look like the user speaking."""

import math
import struct

from app.core.vad import FRAME_BYTES, SAMPLE_RATE, Segmenter


def _tone(frames: int, amplitude: int, freq: float = 220.0) -> bytes:
    """Build 16 kHz PCM16 frames of a voiced-looking sine wave."""
    samples = FRAME_BYTES // 2
    out = bytearray()
    for _ in range(frames):
        for i in range(samples):
            out += struct.pack(
                "<h", int(amplitude * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
            )
    return bytes(out)


class _AlwaysSpeech:
    """Deterministic stand-in for webrtcvad so tests only exercise the gate."""

    def is_speech(self, frame: bytes, rate: int) -> bool:  # noqa: ARG002
        return True


def test_quiet_echo_does_not_start_speech_while_agent_speaks():
    seg = Segmenter()
    seg.vad = _AlwaysSpeech()
    events = []
    for _ in range(30):
        events += seg.feed(_tone(2, 300), is_assistant_speaking=True, energy_floor=4000.0)
    assert not [e for e, _ in events if e in {"speech_start", "barge_in"}]


def test_loud_user_speech_barges_in_over_the_agent():
    seg = Segmenter()
    seg.vad = _AlwaysSpeech()
    events = []
    for _ in range(30):
        events += seg.feed(_tone(2, 9000), is_assistant_speaking=True, energy_floor=4000.0)
    kinds = [e for e, _ in events]
    assert "speech_start" in kinds
    assert "barge_in" in kinds


def test_static_threshold_still_used_without_override():
    seg = Segmenter()
    seg.vad = _AlwaysSpeech()
    events = []
    for _ in range(30):
        events += seg.feed(_tone(2, 900), is_assistant_speaking=False)
    assert "speech_start" in [e for e, _ in events]
