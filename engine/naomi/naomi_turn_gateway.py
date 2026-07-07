"""The Naomi loop gateway: inert construction, lazy real-orchestrator build.

Purpose: one per engine process. Construction is INERT (no keys, no I/O, no
model load) so engine boot never fails on Naomi; the first ``listen.start``
lazily opens the long-lived resources — a database connection (answer service
+ action flow + router ledger), the BM25 retriever, the keyed router, the
loaded Silero/Parakeet models, the persistent Cartesia socket, and the turn
speaker — and wires them into the orchestrator. Delegates the command surface
to that orchestrator.
Pipeline position: constructed by ``engine.server`` / the wiring factory,
driven by ``naomi_turn_command_dispatcher``.

Security invariants: providers resolve per process from the keyed store (a
missing key refuses at first use, never at boot); the persistent connection
checks the kill switch at every (re)connect; audio stays local (mic-only).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import AudioFrame
from engine.index import HybridRrfRetriever
from engine.naomi.naomi_action_intent_flow import NaomiActionIntentFlow
from engine.naomi.naomi_mic_capture_source import start_naomi_mic_capture
from engine.naomi.naomi_turn_orchestrator import NaomiTurnOrchestrator
from engine.naomi.naomi_turn_speaker import NaomiTurnSpeaker
from engine.naomi.naomi_turn_state_machine import NaomiTurnState
from engine.naomi.naomi_voice_answer_service import NaomiVoiceAnswerService
from engine.protocol import EventBroadcastHub
from engine.router import (
    ProviderRouter,
    RouterLedgerEntry,
    build_provider_clients,
    insert_router_ledger_entry,
)
from engine.security import ProviderKeyStore
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.stt.model_weights_downloader import (
    PARAKEET_FILENAME,
    SILERO_VAD_FILENAME,
    models_directory,
)
from engine.stt.parakeet_nemo_transcriber import (
    ParakeetNemoTranscriber,
    stt_dependencies_available,
)
from engine.stt.silero_onnx_voice_activity_detector import SileroOnnxVoiceActivityDetector
from engine.stt.word_token_types import WordToken
from engine.voice.persistent_cartesia_connection import PersistentCartesiaConnection

LedgerRecorder = Callable[[RouterLedgerEntry], Awaitable[None]]
RouterFactory = Callable[[LedgerRecorder], ProviderRouter]


def _default_router_factory(recorder: LedgerRecorder) -> ProviderRouter:
    """Real router: keyed clients only, ledger-bound (built at first use)."""
    return ProviderRouter(build_provider_clients(ProviderKeyStore()), recorder)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class NaomiTurnGateway:
    """Lazily builds and owns the one turn orchestrator for the process."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        db_path: Path,
        migrations_dir: Path,
        *,
        router_factory: RouterFactory | None = None,
        models_dir: Path | None = None,
    ) -> None:
        self._hub = hub
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._router_factory = router_factory or _default_router_factory
        self._models_dir = models_dir if models_dir is not None else models_directory()
        self._orchestrator: NaomiTurnOrchestrator | None = None
        self._transcriber: ParakeetNemoTranscriber | None = None
        self._build_lock = asyncio.Lock()

    @property
    def state(self) -> NaomiTurnState:
        if self._orchestrator is None:
            return NaomiTurnState.IDLE
        return self._orchestrator.state

    async def listen_start(self, open_mic: bool) -> None:
        orchestrator = await self._ensure_orchestrator()
        await orchestrator.listen_start(open_mic)

    async def listen_stop(self, flush: bool) -> None:
        if self._orchestrator is not None:
            await self._orchestrator.listen_stop(flush)

    async def feed_audio_frame(self, frame: AudioFrame) -> None:
        if self._orchestrator is not None:
            await self._orchestrator.feed_audio_frame(frame)

    async def shutdown(self) -> None:
        if self._orchestrator is not None:
            await self._orchestrator.shutdown()

    async def _ensure_orchestrator(self) -> NaomiTurnOrchestrator:
        """Build the orchestrator + its long-lived resources exactly once."""
        async with self._build_lock:
            if self._orchestrator is not None:
                return self._orchestrator
            await apply_migrations(self._db_path, self._migrations_dir)
            connection = await open_sqlite_connection(self._db_path)
            retriever = HybridRrfRetriever(connection, None, None)  # BM25 until vec

            async def record(entry: RouterLedgerEntry) -> None:
                await insert_router_ledger_entry(connection, entry)  # append-only audit

            router = self._router_factory(record)
            answer_service = NaomiVoiceAnswerService(connection, retriever, router)
            action_flow = NaomiActionIntentFlow(
                connection, router, now_iso=_now_iso, clock=time.perf_counter
            )
            vad_factory, transcribe = self._build_stt()
            speaker = NaomiTurnSpeaker(
                self._hub, PersistentCartesiaConnection(), clock=time.monotonic
            )
            orchestrator = NaomiTurnOrchestrator(
                self._hub,
                answer_service,
                action_flow,
                speaker,
                vad_factory,
                transcribe,
                clock=time.monotonic,
                start_capture=start_naomi_mic_capture,
            )
            speaker.set_finished_callback(orchestrator.on_speaker_finished)
            self._orchestrator = orchestrator
            return orchestrator

    def _build_stt(
        self,
    ) -> tuple[
        Callable[[], Callable[[npt.NDArray[np.float32]], float]],
        Callable[[npt.NDArray[np.float32]], Awaitable[list[WordToken]]],
    ]:
        """A fresh-Silero factory + a threaded Parakeet transcribe callable.

        Parakeet is loaded lazily on first use inside the transcribe call —
        heavy work stays off the event loop (heartbeats keep flowing).
        """
        vad_model = self._models_dir / SILERO_VAD_FILENAME

        def vad_factory() -> Callable[[npt.NDArray[np.float32]], float]:
            return SileroOnnxVoiceActivityDetector(vad_model)

        async def transcribe(samples: npt.NDArray[np.float32]) -> list[WordToken]:
            transcriber = await self._ensure_transcriber()
            return await asyncio.to_thread(transcriber.transcribe_window, samples)

        return vad_factory, transcribe

    async def _ensure_transcriber(self) -> ParakeetNemoTranscriber:
        if self._transcriber is None:
            if not stt_dependencies_available():
                raise RuntimeError("STT dependencies not installed (uv sync --extra stt)")
            self._transcriber = ParakeetNemoTranscriber(self._models_dir / PARAKEET_FILENAME)
        if not self._transcriber.is_loaded:
            await asyncio.to_thread(self._transcriber.load)
        return self._transcriber
