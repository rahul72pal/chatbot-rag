"""Dual-Layer Voice Activity Detection (VAD) Segmenter.

Combines Layer 1 (Energy RMS Thresholding with temporal windowing) and
Layer 2 (ML-based WebRTC VAD) to eliminate false interruptions from keyboard
clicks, background noise, breathing, and acoustic echo, while reliably detecting
genuine user speech and barge-in.
"""

from __future__ import annotations

from collections import deque
import numpy as np
import webrtcvad

SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2  # 640 bytes for 20ms at 16kHz PCM16


class Segmenter:
    """Dual-Layer VAD Segmenter for 16 kHz Mono signed PCM16 audio.

    Layer 1: Energy RMS thresholding with temporal windowing (requires sustained
             activity over 200-240ms, ignoring transient ~50ms clicks/breaths).
    Layer 2: ML-based WebRTC VAD (validates genuine human vocal characteristics).
    """

    def __init__(
        self,
        aggressiveness: int = 3,
        energy_threshold: float = 650.0,
        barge_in_energy_threshold: float = 950.0,
        window_ms: int = 140,
        trigger_ratio: float = 0.50,
        end_silence_ms: int = 320,
        barge_in_end_silence_ms: int = 360,
        min_utterance_ms: int = 280,
        min_utterance_rms: float = 550.0,
        preroll_frames: int = 15,
        max_utterance_ms: int = 60_000,
    ) -> None:
        # Keep short and quieter speech responsive while RMS gating still filters noise.
        self.vad = webrtcvad.Vad(aggressiveness)

        # Configurable thresholds
        self.energy_threshold = float(energy_threshold)
        self.barge_in_energy_threshold = float(barge_in_energy_threshold)
        self.min_utterance_rms = float(min_utterance_rms)
        self.window_frames = max(4, window_ms // FRAME_MS)
        self.trigger_ratio = trigger_ratio
        self.end_silence_ms = end_silence_ms
        self.barge_in_end_silence_ms = barge_in_end_silence_ms
        self.min_utterance_ms = min_utterance_ms
        self.max_utterance_bytes = SAMPLE_RATE * 2 * max_utterance_ms // 1000

        # Dynamic ambient noise floor tracking (initialized to typical quiet room baseline)
        self.noise_floor = 180.0

        # Buffers & state
        self.pending = bytearray()
        self.preroll: deque[bytes] = deque(maxlen=preroll_frames)
        self.recent_activity: deque[bool] = deque(maxlen=self.window_frames)
        self.utterance = bytearray()
        self.in_speech = False
        self.silence_ms = 0

    @staticmethod
    def calculate_rms(frame: bytes) -> float:
        """Calculate Root Mean Square (RMS) energy of a 16-bit signed PCM frame."""
        if not frame:
            return 0.0
        samples = np.frombuffer(frame, dtype=np.int16)
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))

    def feed(
        self,
        chunk: bytes,
        is_assistant_speaking: bool = False,
        energy_floor: float | None = None,
    ) -> list[tuple[str, bytes | None]]:
        """Process incoming 16kHz PCM16 bytes and emit VAD events.

        Returns list of (event_type, payload):
            - ("speech_start", None): Genuine speech activity confirmed by dual layers.
            - ("barge_in", None): User interrupted while assistant was speaking.
            - ("utterance", bytes): Completed speech audio ready for transcription.
            - ("utterance_too_long", None): Utterance exceeded safety limit.

        ``energy_floor`` can override the microphone RMS threshold when a
        calibrated microphone-specific floor is available. Outgoing speaker
        audio must not be used as this threshold.
        """
        events: list[tuple[str, bytes | None]] = []
        self.pending.extend(chunk)

        if energy_floor is not None:
            energy_floor = float(energy_floor)
        else:
            energy_floor = (
                self.barge_in_energy_threshold
                if is_assistant_speaking
                else self.energy_threshold
            )

        while len(self.pending) >= FRAME_BYTES:
            frame = bytes(self.pending[:FRAME_BYTES])
            del self.pending[:FRAME_BYTES]

            # -----------------------------------------------------------------
            # Layer 1: Energy (RMS) Thresholding & Proximity Noise Gate
            # -----------------------------------------------------------------
            rms = self.calculate_rms(frame)
            # Voice right on mic must exceed near-field threshold AND stay above background room noise floor
            has_energy = (rms >= energy_floor) and (rms >= self.noise_floor * 2.0)

            # -----------------------------------------------------------------
            # Layer 2: WebRTC VAD (ML voice spectrum validation)
            # -----------------------------------------------------------------
            is_voice = False
            if has_energy:
                try:
                    is_voice = self.vad.is_speech(frame, SAMPLE_RATE)
                except Exception:
                    is_voice = False
            else:
                # Track ambient noise floor during non-speech
                self.noise_floor = 0.98 * self.noise_floor + 0.02 * min(rms, energy_floor)

            # Dual-layer confirmation: BOTH Energy AND ML VAD must agree
            is_confirmed_speech = has_energy and is_voice
            self.recent_activity.append(is_confirmed_speech)
            self.preroll.append(frame)

            if self.in_speech:
                self.utterance.extend(frame)
                if len(self.utterance) > self.max_utterance_bytes:
                    self.in_speech = False
                    self.utterance.clear()
                    self.silence_ms = 0
                    self.recent_activity.clear()
                    events.append(("utterance_too_long", None))
                    continue

                if is_confirmed_speech:
                    self.silence_ms = 0
                else:
                    self.silence_ms += FRAME_MS
                    effective_end_silence = (
                        self.barge_in_end_silence_ms
                        if is_assistant_speaking
                        else self.end_silence_ms
                    )
                    if self.silence_ms >= effective_end_silence:
                        self.in_speech = False
                        duration_ms = len(self.utterance) * 1000 // (SAMPLE_RATE * 2)
                        if duration_ms >= self.min_utterance_ms:
                            # Verify average utterance energy to reject distant far-field background voices
                            avg_rms = self.calculate_rms(bytes(self.utterance))
                            if avg_rms >= self.min_utterance_rms:
                                events.append(("utterance", bytes(self.utterance)))
                            else:
                                events.append(("far_field_rejected", None))
                        self.utterance.clear()
                        self.silence_ms = 0
                        self.recent_activity.clear()
            else:
                # In idle or listening state: check sliding window for sustained speech activity
                if len(self.recent_activity) >= self.window_frames:
                    speech_ratio = sum(self.recent_activity) / len(self.recent_activity)
                    if speech_ratio >= self.trigger_ratio:
                        self.in_speech = True
                        self.silence_ms = 0
                        self.utterance = bytearray(b"".join(self.preroll))
                        events.append(("speech_start", None))
                        if is_assistant_speaking:
                            events.append(("barge_in", None))

        return events
