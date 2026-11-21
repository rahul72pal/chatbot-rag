"""Manual public WebSocket client for Phase 7 voice smoke checks.

Example:
    python scripts/voice_ws_client.py sample_16k_mono.wav
    python scripts/voice_ws_client.py first.wav --barge-in-wav second.wav
"""

from __future__ import annotations

import argparse
import asyncio
import json
import wave
from pathlib import Path
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect

FRAME_BYTES = 640  # 20 ms of mono PCM16 at 16 kHz


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as source:
        if (
            source.getframerate() != 16_000
            or source.getnchannels() != 1
            or source.getsampwidth() != 2
        ):
            raise ValueError(f"{path} must be 16 kHz, mono, 16-bit PCM WAV")
        return source.readframes(source.getnframes())


async def send_frames(socket, pcm: bytes) -> None:
    for offset in range(0, len(pcm), FRAME_BYTES):
        frame = pcm[offset : offset + FRAME_BYTES]
        if len(frame) < FRAME_BYTES:
            frame += bytes(FRAME_BYTES - len(frame))
        await socket.send(frame)
        await asyncio.sleep(0.02)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path, help="16 kHz mono PCM16 input WAV")
    parser.add_argument("--barge-in-wav", type=Path, help="optional second utterance sent during TTS")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--language", default="en")
    parser.add_argument("--output", type=Path, default=Path("voice_reply.wav"))
    args = parser.parse_args()

    first_audio = read_pcm(args.wav)
    second_audio = read_pcm(args.barge_in_wav) if args.barge_in_wav else None
    async with httpx.AsyncClient(base_url=args.base_url, timeout=20) as client:
        response = await client.post(
            "/api/v1/voice/session", json={"language": args.language}
        )
        response.raise_for_status()
        session_id = response.json()["session_id"]

    ws_base = args.base_url.replace("https://", "wss://").replace("http://", "ws://")
    url = f"{ws_base}/ws/voice?{urlencode({'session_id': session_id})}"
    audio_output = bytearray()
    output_rate = 24_000
    second_sent = False
    async with connect(url, max_size=2**20) as socket:
        await socket.send(json.dumps({"type": "config", "language": args.language}))
        await send_frames(socket, first_audio)
        await send_frames(socket, bytes(16_000 * 2))  # one second of silence

        while True:
            message = await socket.recv()
            if isinstance(message, bytes):
                audio_output.extend(message)
                continue

            event = json.loads(message)
            print(json.dumps(event, ensure_ascii=False))
            if event.get("type") in {"audio_config", "audio_start"}:
                output_rate = int(event.get("output_sample_rate", event.get("sample_rate", output_rate)))
            if event.get("type") == "interrupt":
                audio_output.clear()  # mirror the browser playback-queue flush
            if event.get("type") == "audio_start" and second_audio and not second_sent:
                second_sent = True
                await send_frames(socket, second_audio)
                await send_frames(socket, bytes(16_000 * 2))
            if event.get("type") == "turn_end":
                break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(output_rate)
        output.writeframes(audio_output)
    print(f"Saved streamed reply audio to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
