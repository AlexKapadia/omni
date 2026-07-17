"""Engine HTTP + WebSocket server and process entrypoint.

Purpose: hosts the pinned surface the UI talks to — GET /health and the
ws://127.0.0.1:<port>/ws protocol-v1 endpoint — and owns process startup
and graceful shutdown. Run with ``python -m engine.server``.
Pipeline position: the outermost shell of the engine sidecar; everything
else in ``engine.*`` is reached through the routes defined here.

Security invariants:
- Binds to 127.0.0.1 ONLY (``LOOPBACK_HOST`` constant) — the engine must
  never be reachable from another machine (local-only invariant).
- Startup fails closed: malformed settings abort the process rather than
  boot on guessed configuration.
- No telemetry: the server calls out to nothing; it only answers. (The
  one exception is the explicit, user-initiated model download tool.)
- Shutdown stops any live capture session so no orphaned audio streams
  outlive the process.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket

from engine import ENGINE_VERSION
from engine.ask.ask_query_command_dispatcher import AskAnswerGateway
from engine.audio.audio_device_listing import list_audio_devices
from engine.audio.devices_list_command_dispatcher import DeviceLister
from engine.enhance import MeetingFinalizationService
from engine.google.calendar_poll_service import CalendarPollService
from engine.naomi.naomi_turn_command_dispatcher import NaomiTurnControl
from engine.protocol import EventBroadcastHub
from engine.runtime_settings import LOOPBACK_HOST, EngineSettings, load_engine_settings
from engine.stt.live_capture_service import LiveCaptureService
from engine.vault import VaultWriteError, resolve_vault_root
from engine.voice import TtsPlaybackStreamer
from engine.websocket_connection_handler import WebSocketConnectionHandler
from engine.wiring.approval_card_build_server_wiring import ApprovalCardBuildWiring
from engine.wiring.approval_cards_gateway import ApprovalCardsGateway
from engine.wiring.detection_server_wiring import DetectionServerWiring
from engine.wiring.dictation_command_dispatcher import DictationCommandGateway
from engine.wiring.live_answers_spotter_wiring import LiveAnswersSpotterWiring
from engine.wiring.live_meeting_enrichment_wiring import LiveMeetingEnrichmentWiring

# The M7 onboarding/settings command surface (5 gateways) is built and owned
# as one unit so this file stays pure routing/lifecycle.
from engine.wiring.onboarding_settings_command_surface import (
    OnboardingSettingsCommandSurface,
    build_onboarding_settings_command_surface,
)

# The real, settings-driven service factories live in one module so this
# file stays pure routing/lifecycle; tests inject fakes through the seams.
from engine.wiring.server_default_service_factories import (
    default_approval_gateway_factory,
    default_ask_gateway_factory,
    default_calendar_poll_factory,
    default_capture_service_factory,
    default_card_build_wiring_factory,
    default_detection_wiring_factory,
    default_dictation_gateway_factory,
    default_enrichment_wiring_factory,
    default_finalization_service_factory,
    default_naomi_loop_factory,
    default_spotter_wiring_factory,
    default_vault_watchdog_factory,
)
from engine.wiring.vault_watchdog_server_wiring import VaultWatchdogServerWiring

# Factory seams (a factory, not an instance, so services are built AFTER
# settings load, against the hub the app owns; tests inject fakes here).
# Ask/dictation/approval are command-driven so they default ON; detection,
# the spotter, card building, and the vault watchdog run on timers/events,
# so they are wired ONLY when a factory is passed (production passes the
# defaults; tests stay hermetic — no background polls or event reactions).
CaptureServiceFactory = Callable[[EventBroadcastHub], LiveCaptureService]
FinalizationServiceFactory = Callable[[EventBroadcastHub], MeetingFinalizationService]
AskGatewayFactory = Callable[[], AskAnswerGateway]
DictationGatewayFactory = Callable[[EventBroadcastHub], DictationCommandGateway]
ApprovalGatewayFactory = Callable[[EventBroadcastHub], ApprovalCardsGateway]
DetectionWiringFactory = Callable[[EventBroadcastHub, LiveCaptureService], DetectionServerWiring]
SpotterWiringFactory = Callable[[EventBroadcastHub], LiveAnswersSpotterWiring]
EnrichmentWiringFactory = Callable[[EventBroadcastHub], LiveMeetingEnrichmentWiring]
CardBuildWiringFactory = Callable[[EventBroadcastHub], ApprovalCardBuildWiring]
VaultWatchdogFactory = Callable[[], VaultWatchdogServerWiring]
CalendarPollFactory = Callable[[EventBroadcastHub], CalendarPollService]
# Return the structural control Protocol (not the concrete gateway) so tests
# can inject a fake; the real gateway satisfies it (return-type covariance).
NaomiLoopFactory = Callable[[EventBroadcastHub], NaomiTurnControl]


def create_app(
    capture_service_factory: CaptureServiceFactory | None = None,
    preload_stt: bool = False,
    finalization_service_factory: FinalizationServiceFactory | None = None,
    ask_gateway_factory: AskGatewayFactory | None = None,
    dictation_gateway_factory: DictationGatewayFactory | None = None,
    approval_gateway_factory: ApprovalGatewayFactory | None = None,
    device_lister: DeviceLister | None = None,
    detection_wiring_factory: DetectionWiringFactory | None = None,
    spotter_wiring_factory: SpotterWiringFactory | None = None,
    enrichment_wiring_factory: EnrichmentWiringFactory | None = None,
    card_build_wiring_factory: CardBuildWiringFactory | None = None,
    vault_watchdog_factory: VaultWatchdogFactory | None = None,
    calendar_poll_factory: CalendarPollFactory | None = None,
    m7_surface: OnboardingSettingsCommandSurface | None = None,
    naomi_loop_gateway_factory: NaomiLoopFactory | None = None,
) -> FastAPI:
    """Build the FastAPI app. Factory form keeps tests isolated per-app.

    ``preload_stt`` starts a background model load at boot so the
    heartbeat's ``stt_ready`` flips true before the first capture.start;
    it defaults OFF so tests (and tooling) never trigger multi-GB loads.
    ``detection_wiring_factory`` / ``spotter_wiring_factory`` default to
    UNWIRED for the same hermeticity reason (they act on timers/broadcast
    events, not commands); production passes the module-level defaults.
    """
    event_hub = EventBroadcastHub()
    factory = capture_service_factory or default_capture_service_factory
    capture_service = factory(event_hub)
    # Naomi voice: relays Cartesia audio to every socket via the same hub.
    # Construction is inert (credentials resolve lazily per utterance).
    voice_streamer = TtsPlaybackStreamer(event_hub)
    # M2 meeting library/finalization: same hub, inert construction.
    finalization_factory = finalization_service_factory or default_finalization_service_factory
    finalization_service = finalization_factory(event_hub)
    # M3 ask + M5 dictation + M4 approval cards: command-driven, inert
    # construction (default ON).
    ask_gateway = (ask_gateway_factory or default_ask_gateway_factory)()
    dictation_gateway = (dictation_gateway_factory or default_dictation_gateway_factory)(event_hub)
    approval_gateway = (approval_gateway_factory or default_approval_gateway_factory)(event_hub)
    # M7 onboarding/settings surfaces: command-driven, inert construction
    # (default ON), owned as one unit; tests inject a fake surface directly.
    m7 = m7_surface or build_onboarding_settings_command_surface(event_hub)
    # M6 detection + M3 live answers: event/timer-driven — wired only when a
    # factory is passed (see docstring). The detection wiring feeds off the
    # loopback VAD tap the capture service carries (probabilities only).
    detection_wiring = (
        detection_wiring_factory(event_hub, capture_service) if detection_wiring_factory else None
    )
    if detection_wiring is not None:
        capture_service.on_loopback_vad_probability = detection_wiring.feed_vad_sample
        m7.settings_gateway.set_detection_settings_listener(
            detection_wiring.apply_detection_settings
        )
    spotter_wiring = spotter_wiring_factory(event_hub) if spotter_wiring_factory else None
    enrichment_wiring = (
        enrichment_wiring_factory(event_hub) if enrichment_wiring_factory else None
    )
    if enrichment_wiring is not None:
        m7.settings_gateway.set_live_translation_settings_listener(
            enrichment_wiring.apply_translation_lang
        )
    # M4 card-building seams (event/hook-driven — same wired-only-when-passed
    # rule): finalization events + the dictation gateway's post-final hook.
    card_build_wiring = card_build_wiring_factory(event_hub) if card_build_wiring_factory else None
    if card_build_wiring is not None:
        dictation_gateway.on_final_result = card_build_wiring.on_dictation_final

        # Instant-execute whitelist seam: a whitelisted dictation card runs the
        # SAME audited approve->execute path (never a bypass of the audit); the
        # whitelist itself is read per intent from app_settings (deny default).
        card_build_wiring.auto_execute_whitelisted = (
            lambda card_id: approval_gateway.approve(card_id, None)
        )
    # M3 live vault watching (OS-event-driven — same rule).
    vault_watchdog = vault_watchdog_factory() if vault_watchdog_factory else None
    vault_rebind_tasks: list[asyncio.Task[None]] = []
    if vault_watchdog is not None:
        # Mid-session vault_dir change: stop the old observer and watch the new root.
        def _rebind_vault_watcher(vault_dir: str) -> None:
            loop = asyncio.get_running_loop()
            # Keep a strong ref so the task is not GC'd mid-flight (RUF006).
            vault_rebind_tasks.append(
                loop.create_task(vault_watchdog.rebind(Path(vault_dir)))
            )

        m7.settings_gateway.set_vault_dir_listener(_rebind_vault_watcher)
    calendar_poll = calendar_poll_factory(event_hub) if calendar_poll_factory else None
    # Naomi conversation loop: command-driven but heavy (loads STT models,
    # opens the mic + persistent Cartesia socket on first listen), so wired
    # ONLY when a factory is passed — hermetic tests get an honest refusal.
    naomi_loop_gateway = (
        naomi_loop_gateway_factory(event_hub) if naomi_loop_gateway_factory else None
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Startup: clocks, preload, detection poll. Shutdown: stop everything."""
        app.state.started_monotonic = time.monotonic()
        preload_task: asyncio.Task[None] | None = None
        if preload_stt:
            # Production marker: make persisted settings effective before the
            # first command — a user-chosen vault and an engaged kill switch
            # survive restarts (fail closed on egress across reboots).
            await m7.apply_persisted_settings_at_boot()
            if detection_wiring is not None:
                payload = await m7.settings_gateway.get_settings_payload()
                settings = payload.get("settings")
                if isinstance(settings, dict):
                    detection_wiring.apply_detection_settings(settings)
            # Background: heartbeats flow (stt_ready=false) while models load.
            preload_task = asyncio.create_task(capture_service.preload_models())
        if detection_wiring is not None:
            detection_wiring.start()  # bot-free detection poll loop
        if vault_watchdog is not None:
            # Factory may have resolved vault BEFORE boot applied DB vault_dir
            # into OMNI_VAULT_DIR — rebind so a DB-only vault is watched.
            if preload_stt:
                try:
                    await vault_watchdog.rebind(resolve_vault_root())
                except VaultWriteError:
                    vault_watchdog.start()  # honest OFF when still unconfigured
            else:
                vault_watchdog.start()  # live vault reindex (or one honest OFF line)
        if calendar_poll is not None:
            calendar_poll.start()
        yield
        if detection_wiring is not None:
            # Stop the poll loop first: no suggestions during teardown.
            with contextlib.suppress(Exception):
                await detection_wiring.stop()
        if vault_watchdog is not None:
            with contextlib.suppress(Exception):
                await vault_watchdog.shutdown()
        if calendar_poll is not None:
            with contextlib.suppress(Exception):
                await calendar_poll.stop()
        if spotter_wiring is not None:
            with contextlib.suppress(Exception):
                await spotter_wiring.shutdown()
        if enrichment_wiring is not None:
            with contextlib.suppress(Exception):
                await enrichment_wiring.shutdown()
        if card_build_wiring is not None:
            with contextlib.suppress(Exception):
                await card_build_wiring.shutdown()
        # In-flight card executions get a short grace, then cancel.
        with contextlib.suppress(Exception):
            await approval_gateway.shutdown()
        # A running model download or Google consent flow is cancelled so no
        # background task outlives the process.
        await m7.shutdown()
        if preload_task is not None and not preload_task.done():
            preload_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await preload_task
        if capture_service.is_capturing:
            # Graceful shutdown: never orphan live audio streams.
            with contextlib.suppress(Exception):
                await capture_service.stop()
        # Graceful shutdown: never orphan a speaking utterance either.
        with contextlib.suppress(Exception):
            await voice_streamer.shutdown()
        # Naomi loop: stop capture, silence the speaker, close the socket.
        if naomi_loop_gateway is not None:
            with contextlib.suppress(Exception):
                await naomi_loop_gateway.shutdown()

    app = FastAPI(
        title="omni-engine",
        version=ENGINE_VERSION,
        # No public docs surface: the engine is a private local sidecar,
        # not a browsable API (minimise attack/discovery surface).
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.event_hub = event_hub
    app.state.capture_service = capture_service
    app.state.voice_streamer = voice_streamer
    app.state.finalization_service = finalization_service
    app.state.ask_gateway = ask_gateway
    app.state.dictation_gateway = dictation_gateway
    app.state.approval_gateway = approval_gateway
    app.state.device_lister = device_lister if device_lister is not None else list_audio_devices
    app.state.detection_wiring = detection_wiring
    app.state.spotter_wiring = spotter_wiring
    app.state.enrichment_wiring = enrichment_wiring
    app.state.card_build_wiring = card_build_wiring
    app.state.vault_watchdog = vault_watchdog
    app.state.m7_surface = m7
    app.state.naomi_loop_gateway = naomi_loop_gateway

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness probe for the UI supervisor and the packaging smoke test."""
        return {"status": "ok", "version": ENGINE_VERSION}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Protocol v1 endpoint: accept, then hand off to the handler."""
        await websocket.accept()
        state = websocket.app.state
        detection = state.detection_wiring
        handler = WebSocketConnectionHandler(
            websocket=websocket,
            started_monotonic=state.started_monotonic,
            capture_service=state.capture_service,
            event_hub=state.event_hub,
            voice_streamer=state.voice_streamer,
            finalization_service=state.finalization_service,
            ask_gateway=state.ask_gateway,
            dictation_gateway=state.dictation_gateway,
            approval_gateway=state.approval_gateway,
            # detection.dismiss needs the service; None → honest refusal.
            detection_service=detection.service if detection is not None else None,
            device_lister=state.device_lister,
            m7_surface=state.m7_surface,
            naomi_loop_control=state.naomi_loop_gateway,
        )
        await handler.run()

    return app


def build_uvicorn_config(settings: EngineSettings) -> uvicorn.Config:
    """Translate validated settings into the uvicorn config.

    Split out from ``main`` so tests can assert the binding contract
    (loopback-only host, env-driven port) without opening a socket.
    """
    return uvicorn.Config(
        # Production app: STT preloads at boot, and the event/timer-driven
        # reconciliation surfaces (M6 detection, M3 live answers, M4 card
        # building, live vault watching) are wired.
        app=create_app(
            preload_stt=True,
            detection_wiring_factory=default_detection_wiring_factory,
            spotter_wiring_factory=default_spotter_wiring_factory,
            enrichment_wiring_factory=default_enrichment_wiring_factory,
            card_build_wiring_factory=default_card_build_wiring_factory,
            vault_watchdog_factory=default_vault_watchdog_factory,
            calendar_poll_factory=default_calendar_poll_factory,
            naomi_loop_gateway_factory=default_naomi_loop_factory,
        ),
        # Local-only invariant: loopback constant, never a setting.
        host=LOOPBACK_HOST,
        port=settings.engine_port,
        log_level="info",
        # The Tauri supervisor restarts us; workers stay at 1 so there is
        # exactly one heartbeat/state owner per process.
        workers=1,
    )


def main() -> None:
    """Process entrypoint: load settings (fail closed) and serve until signalled."""
    # Root logging at INFO: the engine log is the audit surface for capture
    # lifecycle and the 60 s p50/p95 latency lines (instrumentation mandate)
    # — uvicorn only configures its own loggers, never the root.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    server = uvicorn.Server(build_uvicorn_config(settings))
    # uvicorn installs SIGINT/SIGTERM handlers → graceful shutdown of the
    # event loop and open WebSockets.
    server.run()


if __name__ == "__main__":
    main()
