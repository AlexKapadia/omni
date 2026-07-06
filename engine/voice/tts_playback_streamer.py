"""TTS playback streamer: Cartesia messages → naomi.* events on the hub.

Purpose: owns one active utterance at a time — dispatches the Cartesia
stream as a background task, relays audio chunks / word timestamps to every
connected UI socket via the EventBroadcastHub, measures the honest TTFA
(say-dispatch → first audio chunk), and implements cancel/barge-in: a new
``say`` silences the previous utterance first.
Pipeline position: between the naomi command dispatcher (or, post-M2/M3,
the turn orchestrator) and the Cartesia client; broadcasts through the same
hub pattern as capture/transcript events.

Security invariants:
- Kill switch checked here AND in the client (defence in depth): engaged
  means no client is built and nothing is dispatched (fail closed).
- Credentials resolve lazily per utterance via the credentials module —
  this class never touches key material itself.
"""

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable

from engine.protocol import EventBroadcastHub
from engine.security import kill_switch_engaged
from engine.voice.cartesia_credentials import load_cartesia_credentials
from engine.voice.cartesia_message_framing import (
    CartesiaAudioChunk,
    CartesiaDone,
    CartesiaErrorMessage,
    CartesiaWordTimestamps,
)
from engine.voice.cartesia_streaming_tts_client import CartesiaStreamingTtsClient
from engine.voice.naomi_voice_event_payloads import (
    EVENT_NAOMI_AUDIO_CHUNK,
    EVENT_NAOMI_AUDIO_DONE,
    EVENT_NAOMI_SPEAKING_TIMESTAMPS,
    build_naomi_audio_chunk_payload,
    build_naomi_audio_done_payload,
    build_naomi_speaking_timestamps_payload,
)
from engine.voice.voice_errors import VoiceEgressBlockedError, VoiceProviderError

ClientFactory = Callable[[], CartesiaStreamingTtsClient]


def _default_client_factory() -> CartesiaStreamingTtsClient:
    """Fresh client with env credentials — raises VoiceNotConfiguredError
    (fail closed) when the key/voice are absent."""
    return CartesiaStreamingTtsClient(load_cartesia_credentials())


class TtsPlaybackStreamer:
    """One speaking mouth: at most one live utterance, always cancellable."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        client_factory: ClientFactory | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._hub = hub
        self._client_factory = client_factory or _default_client_factory
        self._clock = clock
        self._active_task: asyncio.Task[None] | None = None
        self._active_context_id: str | None = None
        self._active_client: CartesiaStreamingTtsClient | None = None

    @property
    def active_context_id(self) -> str | None:
        return self._active_context_id

    async def say(self, text: str, affect: tuple[float, float] | None) -> str:
        """Start speaking ``text``; returns the new utterance's context_id.

        Barge-in semantics: any current utterance is cancelled FIRST, so
        Naomi never talks over herself. Raises VoiceEgressBlockedError /
        VoiceNotConfiguredError before anything is dispatched (fail closed).
        """
        # Defence in depth: the client checks again before connecting, but
        # refusing HERE means no task, no client, no partial state at all.
        if kill_switch_engaged():
            raise VoiceEgressBlockedError()
        client = self._client_factory()  # may raise VoiceNotConfiguredError
        await self.cancel()  # silence the previous utterance first
        context_id = str(uuid.uuid4())
        self._active_context_id = context_id
        self._active_client = client
        self._active_task = asyncio.create_task(self._relay(client, text, context_id, affect))
        return context_id

    async def cancel(self) -> str | None:
        """Cancel the live utterance (the wire half of barge-in).

        Sends Cartesia the cancel frame, stops the relay task, and
        broadcasts ``naomi.audio.done`` (cancelled). Returns the cancelled
        context_id, or None when nothing was speaking (idempotent).
        """
        task = self._active_task
        context_id = self._active_context_id
        client = self._active_client
        self._active_task = None
        self._active_context_id = None
        self._active_client = None
        if task is None or context_id is None:
            return None
        if client is not None:
            # Stop generation at the source; a no-op if already finished.
            with contextlib.suppress(Exception):
                await client.cancel(context_id)
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await self._hub.broadcast_event(
                EVENT_NAOMI_AUDIO_DONE, build_naomi_audio_done_payload(context_id, "cancelled")
            )
            return context_id
        return None  # relay already finished and reported its own done

    async def shutdown(self) -> None:
        """Process shutdown: never orphan a speaking task."""
        await self.cancel()

    async def _relay(
        self,
        client: CartesiaStreamingTtsClient,
        text: str,
        context_id: str,
        affect: tuple[float, float] | None,
    ) -> None:
        """Stream one utterance from Cartesia onto the event hub."""
        dispatched_at = self._clock()
        seq = 0
        try:
            async for message in client.stream_utterance(text, context_id, affect):
                if isinstance(message, CartesiaAudioChunk):
                    # Honest TTFA: measured from say-dispatch to the FIRST
                    # audio chunk, on this machine, this network — never the
                    # vendor's marketing number.
                    ttfa_ms = (self._clock() - dispatched_at) * 1000 if seq == 0 else None
                    await self._hub.broadcast_event(
                        EVENT_NAOMI_AUDIO_CHUNK,
                        build_naomi_audio_chunk_payload(context_id, seq, message.data_b64, ttfa_ms),
                    )
                    seq += 1
                elif isinstance(message, CartesiaWordTimestamps):
                    await self._hub.broadcast_event(
                        EVENT_NAOMI_SPEAKING_TIMESTAMPS,
                        build_naomi_speaking_timestamps_payload(
                            context_id, message.words, message.starts_s, message.ends_s
                        ),
                    )
                elif isinstance(message, CartesiaDone):
                    await self._hub.broadcast_event(
                        EVENT_NAOMI_AUDIO_DONE,
                        build_naomi_audio_done_payload(context_id, "completed"),
                    )
                elif isinstance(message, CartesiaErrorMessage):
                    await self._hub.broadcast_event(
                        EVENT_NAOMI_AUDIO_DONE,
                        build_naomi_audio_done_payload(context_id, "error", message.message),
                    )
        except (VoiceProviderError, VoiceEgressBlockedError) as exc:
            # Redacted upstream; surface the honest failure to the UI.
            await self._hub.broadcast_event(
                EVENT_NAOMI_AUDIO_DONE,
                build_naomi_audio_done_payload(context_id, "error", str(exc)),
            )
        finally:
            # Clear only OUR context — a newer say() may already own the slots.
            if self._active_context_id == context_id:
                self._active_task = None
                self._active_context_id = None
                self._active_client = None
