"""Warm-socket speaker for the turn loop: clause chunks → relayed audio.

Purpose: speaks Naomi's reply over the PERSISTENT Cartesia socket (so TTFA
never pays the TLS+WSS handshake again — brief §7), one multiplexed
``context_id`` per turn, clause chunks framed ``continue:true`` (last
``continue:false``). It relays audio/timestamps/done onto the SAME event hub
and event names the dev ``naomi.say`` path already uses, measures the honest
warm TTFA (dispatch → first audio chunk), and exposes ``cancel`` as the
wire half of barge-in. Completion is signalled up so the orchestrator can
advance the turn state machine.
Pipeline position: owned by ``engine.naomi.naomi_turn_orchestrator``; wraps
``engine.voice.persistent_cartesia_connection`` and broadcasts through
``engine.protocol.EventBroadcastHub`` exactly like ``TtsPlaybackStreamer``.

Security invariants: the persistent connection checks the kill switch at
every (re)connect and scrubs key material from every error (defence lives
there); this speaker only relays already-safe frames and bounded errors.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable, Sequence

from engine.protocol import EventBroadcastHub
from engine.voice.cartesia_message_framing import (
    CartesiaAudioChunk,
    CartesiaDone,
    CartesiaErrorMessage,
    CartesiaWordTimestamps,
)
from engine.voice.naomi_voice_event_payloads import (
    EVENT_NAOMI_AUDIO_CHUNK,
    EVENT_NAOMI_AUDIO_DONE,
    EVENT_NAOMI_SPEAKING_TIMESTAMPS,
    build_naomi_audio_chunk_payload,
    build_naomi_audio_done_payload,
    build_naomi_speaking_timestamps_payload,
)
from engine.voice.persistent_cartesia_connection import PersistentCartesiaConnection
from engine.voice.voice_errors import VoiceEgressBlockedError, VoiceProviderError

# Callbacks up to the orchestrator.
FirstAudioCallback = Callable[[int], Awaitable[None]]  # (ttfa_ms,)
FinishedCallback = Callable[[str, str], Awaitable[None]]  # (context_id, reason)

_CLOCK = Callable[[], float]


class NaomiTurnSpeaker:
    """One speaking mouth over the warm socket: at most one live utterance."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        connection: PersistentCartesiaConnection,
        *,
        clock: _CLOCK,
        on_finished: FinishedCallback | None = None,
    ) -> None:
        self._hub = hub
        self._connection = connection
        self._clock = clock
        self._on_finished = on_finished
        self._active_task: asyncio.Task[None] | None = None
        self._active_context_id: str | None = None

    @property
    def active_context_id(self) -> str | None:
        return self._active_context_id

    def set_finished_callback(self, on_finished: FinishedCallback) -> None:
        """Wire the completion callback (the orchestrator, built after this)."""
        self._on_finished = on_finished

    async def speak(
        self,
        chunks: Sequence[str],
        affect: tuple[float, float] | None,
        on_first_audio: FirstAudioCallback | None = None,
    ) -> str:
        """Begin speaking ``chunks``; returns the new utterance's context_id.

        Any current utterance is cancelled FIRST so Naomi never overlaps
        herself. The relay runs as a background task; ``on_first_audio`` is
        awaited once, with the measured warm TTFA, on the first audio chunk.
        """
        await self.cancel()  # silence any previous utterance first
        context_id = str(uuid.uuid4())
        self._active_context_id = context_id
        self._active_task = asyncio.create_task(
            self._relay(tuple(chunks), context_id, affect, on_first_audio)
        )
        return context_id

    async def cancel(self) -> str | None:
        """Cancel the live utterance (barge-in wire); idempotent.

        Sends Cartesia the cancel frame for the active context, stops the
        relay, and broadcasts ``naomi.audio.done`` (cancelled). Returns the
        cancelled context_id, or None when nothing was speaking.
        """
        task = self._active_task
        context_id = self._active_context_id
        self._active_task = None
        self._active_context_id = None
        if task is None or context_id is None:
            return None
        # Stop generation at the source (no-op if already finished/torn).
        with contextlib.suppress(Exception):
            await self._connection.cancel(context_id)
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await self._hub.broadcast_event(
                EVENT_NAOMI_AUDIO_DONE,
                build_naomi_audio_done_payload(context_id, "cancelled"),
            )
            return context_id
        return None  # relay already finished and reported its own done

    async def shutdown(self) -> None:
        """Process shutdown: silence anything speaking, close the socket."""
        await self.cancel()
        await self._connection.close()

    async def _relay(
        self,
        chunks: tuple[str, ...],
        context_id: str,
        affect: tuple[float, float] | None,
        on_first_audio: FirstAudioCallback | None,
    ) -> None:
        """Stream one utterance from the warm socket onto the event hub."""
        dispatched_at = self._clock()
        seq = 0
        reason = "completed"
        try:
            async for message in self._connection.speak_utterance(chunks, context_id, affect):
                if isinstance(message, CartesiaAudioChunk):
                    ttfa_ms: int | None = None
                    if seq == 0:
                        # Honest WARM TTFA: dispatch → first audio, this
                        # machine, this network — no handshake in the number.
                        ttfa_ms = round((self._clock() - dispatched_at) * 1000)
                        if on_first_audio is not None:
                            await on_first_audio(ttfa_ms)
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
                    reason = "error"
                    await self._hub.broadcast_event(
                        EVENT_NAOMI_AUDIO_DONE,
                        build_naomi_audio_done_payload(context_id, "error", message.message),
                    )
        except (VoiceProviderError, VoiceEgressBlockedError) as exc:
            reason = "error"
            await self._hub.broadcast_event(
                EVENT_NAOMI_AUDIO_DONE,
                build_naomi_audio_done_payload(context_id, "error", str(exc)),
            )
        finally:
            if self._active_context_id == context_id:
                self._active_task = None
                self._active_context_id = None
                # Signal completion so the orchestrator advances the turn
                # (only for a natural end — a cancel() path reports its own).
                if self._on_finished is not None:
                    await self._on_finished(context_id, reason)
