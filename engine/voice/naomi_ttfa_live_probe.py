"""Manual live TTFA probe: ONE real Cartesia call, honest measurement.

Purpose: the single deliberately-networked dev tool that measures the real
time-to-first-audio on this machine — dispatch → first PCM chunk — so the
latency budget row "TTS first audio" carries a MEASURED number, never the
vendor's marketing claim. Run explicitly:

    uv run python -m engine.voice.naomi_ttfa_live_probe "Hello from Naomi."

Requires CARTESIA_API_KEY / CARTESIA_VOICE_ID in the process environment
(the dev runner loads .env; this module never reads .env itself).

NOT part of the test suite: unit tests are hermetic (no network, §5.5);
this probe is the clearly-separated one real call the build gate asks for.

Security invariants: prints byte counts and millisecond timings ONLY —
never key material, never the voice id, never raw payloads.
"""

import asyncio
import base64
import sys
import time

from engine.voice.cartesia_credentials import load_cartesia_credentials
from engine.voice.cartesia_message_framing import (
    CartesiaAudioChunk,
    CartesiaDone,
    CartesiaErrorMessage,
    CartesiaWordTimestamps,
)
from engine.voice.cartesia_streaming_tts_client import CartesiaStreamingTtsClient


async def measure_ttfa(text: str) -> int:
    """Stream one utterance; print timings; return a process exit code."""
    client = CartesiaStreamingTtsClient(load_cartesia_credentials())
    dispatched = time.monotonic()
    first_chunk_ms: float | None = None
    total_pcm_bytes = 0
    chunk_count = 0
    word_count = 0
    async for message in client.stream_utterance(text, "ttfa-probe", affect=None):
        if isinstance(message, CartesiaAudioChunk):
            if first_chunk_ms is None:
                first_chunk_ms = (time.monotonic() - dispatched) * 1000
            chunk_count += 1
            total_pcm_bytes += len(base64.b64decode(message.data_b64))
        elif isinstance(message, CartesiaWordTimestamps):
            word_count += len(message.words)
        elif isinstance(message, CartesiaDone):
            break
        elif isinstance(message, CartesiaErrorMessage):
            print(f"PROVIDER ERROR: {message.message[:200]}")
            return 1
    total_ms = (time.monotonic() - dispatched) * 1000
    if first_chunk_ms is None:
        print("FAILED: stream ended with zero audio chunks")
        return 1
    audio_seconds = total_pcm_bytes / 4 / 24000  # f32 mono @ 24kHz
    print(f"TTFA (dispatch -> first audio chunk): {first_chunk_ms:.0f} ms")
    print(f"total stream time: {total_ms:.0f} ms")
    print(f"chunks: {chunk_count} · pcm bytes: {total_pcm_bytes} · audio: {audio_seconds:.2f}s")
    print(f"word timestamps received: {word_count}")
    return 0


def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello. Naomi is measuring her own voice."
    sys.exit(asyncio.run(measure_ttfa(text)))


if __name__ == "__main__":
    main()
