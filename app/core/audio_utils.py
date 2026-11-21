"""Audio container helpers for the voice pipeline."""

import io
import wave
import numpy as np
from scipy import signal

# Butterworth high-pass filter coefficients at 85Hz for 16kHz audio to remove low-frequency fan/room rumble
_B_HP, _A_HP = signal.butter(2, 85.0 / (16000 / 2), btype="high")


def suppress_noise_pcm16(pcm: bytes, sample_rate: int = 16_000) -> bytes:
    """Apply high-pass rumble suppression and DC-bias removal to 16-bit PCM audio."""
    if not pcm or len(pcm) < 4:
        return pcm
    try:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        # 1. Remove DC bias
        samples -= np.mean(samples)
        # 2. Filter low-frequency ambient rumble (< 85Hz)
        filtered = signal.lfilter(_B_HP, _A_HP, samples)
        # 3. Clip and convert back to int16
        filtered_int16 = np.clip(filtered, -32768, 32767).astype(np.int16)
        return filtered_int16.tobytes()
    except Exception:
        return pcm


def pcm16_to_wav(pcm: bytes, sample_rate: int = 16_000) -> bytes:
    """Wrap mono signed PCM16 bytes in a WAV container for transcription APIs."""
    if len(pcm) % 2:
        raise ValueError("PCM16 audio must contain complete 16-bit samples.")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()
