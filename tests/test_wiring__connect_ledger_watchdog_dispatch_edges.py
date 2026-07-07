"""Adversarial error/refusal paths across the remaining M6/M7 server wiring.

Google-connect (single-flight refusal, fail-closed completion, shutdown
cancel), ledger summary (unwired + read-failure), the vault watchdog
(loop-race drop, swallowed indexing failure, straggler-flush cancel),
detection (VAD delegation + unmappable-decision drop), the live-answers
spotter (default factory, non-event ignore, session-start failure, worker
survives spotter faults), dictation finalizer construction, and provider-key
custody failures. No network anywhere: downstream services are faked or
patched in-process, and every gateway runs over a tmp database.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

import engine.wiring.dictation_command_dispatcher as dictation_mod
import engine.wiring.google_connect_command_dispatcher as google_mod
import engine.wiring.live_answers_spotter_wiring as spotter_mod
import engine.wiring.provider_keys_command_dispatcher as keys_mod
from engine.detect import (
    AutoStartRulesEngine,
    DesktopSnapshot,
    DetectionService,
    MeetingProcessWatcher,
    MicrophoneInUseDetector,
    SustainedLoopbackVadTrigger,
)
from engine.dictation.dictation_finalization import DictationReleaseFinalizer
from engine.protocol import (
    EVENT_CAPTURE_STARTED,
    EVENT_CAPTURE_STOPPED,
    EVENT_TRANSCRIPT_FINAL,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
)
from engine.security.provider_key_store import ProviderKeyStore
from engine.security.secret_redaction import SecretApiKey
from engine.storage import apply_migrations, open_sqlite_connection
from engine.wiring.detection_server_wiring import DetectionServerWiring
from engine.wiring.dictation_command_dispatcher import DictationCommandGateway
from engine.wiring.google_connect_command_dispatcher import (
    GoogleConnectCommandGateway,
    dispatch_google_command,
)
from engine.wiring.ledger_summary_command_dispatcher import (
    LedgerSummaryCommandGateway,
    dispatch_ledger_command,
)
from engine.wiring.live_answers_spotter_wiring import LiveAnswersSpotterWiring
from engine.wiring.provider_keys_command_dispatcher import (
    ProviderKeysCommandGateway,
    dispatch_keys_command,
)
from engine.wiring.vault_watchdog_server_wiring import VaultWatchdogServerWiring
from tests.conftest import REPO_ROOT

MIGRATIONS = REPO_ROOT / "migrations"

SendFn = Callable[[Envelope], Awaitable[None]]


def _collector() -> tuple[list[Envelope], SendFn]:
    sent: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        sent.append(envelope)

    return sent, send


def _event_sink(hub: EventBroadcastHub) -> list[Envelope]:
    events: list[Envelope] = []

    async def subscriber(envelope: Envelope) -> None:
        events.append(envelope)

    hub.subscribe(subscriber)
    return events


def _cmd(name: str, payload: dict[str, object], cid: str = "c1") -> Envelope:
    return Envelope(v=1, kind=EnvelopeKind.COMMAND, name=name, id=cid, payload=payload)


def _event(name: str, payload: dict[str, object]) -> Envelope:
    return Envelope(v=1, kind=EnvelopeKind.EVENT, name=name, id="e1", payload=payload)


# ------------------------------------------------------- google connect


async def test_google_connect_generic_failure_reports_honest_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(store: object) -> None:
        raise RuntimeError("the browser vanished")

    monkeypatch.setattr(google_mod, "run_google_oauth_desktop_flow", boom)
    hub = EventBroadcastHub()
    events = _event_sink(hub)
    gateway = GoogleConnectCommandGateway(hub)
    assert gateway.begin_connect(None, None) is True
    task = gateway._task
    assert task is not None
    await task
    completed = [e for e in events if e.name == "google.connect.completed"]
    assert completed and completed[0].payload["ok"] is False
    # No token/credential material rides the event — only a plain reason.
    assert completed[0].payload["message"] == "the Google connection did not complete"


async def test_second_connect_is_refused_and_shutdown_cancels_the_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def hang(store: object) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(google_mod, "run_google_oauth_desktop_flow", hang)
    hub = EventBroadcastHub()
    gateway = GoogleConnectCommandGateway(hub)
    assert gateway.begin_connect(None, None) is True
    await started.wait()
    assert gateway.is_connecting() is True
    # Single-flight guard: a second consent while one runs is refused, not raced.
    assert gateway.begin_connect(None, None) is False
    task = gateway._task
    await gateway.shutdown()
    assert task is not None and task.cancelled()  # no flow outlives the process


async def test_google_dispatch_rejects_extra_fields() -> None:
    hub = EventBroadcastHub()
    gateway = GoogleConnectCommandGateway(hub)
    sent, send = _collector()
    await dispatch_google_command(_cmd("google.connect", {"scopes": "*"}), gateway, send)
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "invalid_payload"
    assert gateway.is_connecting() is False  # never started on a bad payload


# --------------------------------------------------------- ledger summary


async def test_ledger_dispatch_refuses_when_unavailable() -> None:
    sent, send = _collector()
    await dispatch_ledger_command(_cmd("ledger.summary", {}), None, send)
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "unknown_command"


async def test_ledger_dispatch_reports_read_failure(tmp_db_path: Path) -> None:
    gateway = LedgerSummaryCommandGateway(
        db_path=tmp_db_path, migrations_dir=Path("no-such-migrations-dir")
    )
    sent, send = _collector()
    await dispatch_ledger_command(_cmd("ledger.summary", {}), gateway, send)
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "ledger_error"
    assert "could not be read" in str(sent[0].payload["message"])


# ---------------------------------------------------------- vault watchdog


async def test_late_watcher_event_is_dropped_when_loop_absent(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    wiring = VaultWatchdogServerWiring(tmp_db_path, MIGRATIONS, vault_root=tmp_path)
    # start() was never called, so there is no loop: a late OS event is dropped.
    wiring._on_change_from_watcher_thread([tmp_path / "note.md"])
    assert wiring._pending == set()  # nothing queued, no crash


async def test_indexing_pass_failure_is_swallowed_and_clears_pending(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    wiring = VaultWatchdogServerWiring(
        tmp_path / "db.sqlite",
        Path("no-such-migrations-dir"),
        vault_root=tmp_path,
        debounce_seconds=0.0,
    )
    wiring._pending.add(tmp_path / "note.md")
    with caplog.at_level(logging.ERROR, logger="engine.wiring.vault_watchdog_server_wiring"):
        await wiring._debounce_and_flush()  # one bad pass must not end watching
    assert wiring._pending == set()  # drained despite the failure
    assert "indexing pass failed" in caplog.text


async def test_watchdog_shutdown_cancels_a_running_flush(tmp_path: Path) -> None:
    wiring = VaultWatchdogServerWiring(
        tmp_path / "db.sqlite", MIGRATIONS, vault_root=tmp_path, debounce_seconds=100.0
    )
    wiring._loop = asyncio.get_running_loop()
    wiring._note_changes((tmp_path / "note.md",))
    task = wiring._flush_task
    assert task is not None and not task.done()
    await wiring.shutdown()
    assert task.cancelled()


# -------------------------------------------------------------- detection


def _inert_detection_service(
    on_decision: Callable[[object], None], trigger: SustainedLoopbackVadTrigger
) -> DetectionService:
    return DetectionService(
        process_watcher=MeetingProcessWatcher(lambda: DesktopSnapshot((), ())),
        microphone_detector=MicrophoneInUseDetector(lambda: ()),
        vad_trigger=trigger,
        rules_engine=AutoStartRulesEngine(),
        is_capture_active=lambda: False,
        on_decision=on_decision,  # type: ignore[arg-type]
    )


def test_feed_vad_sample_delegates_to_the_service() -> None:
    hub = EventBroadcastHub()
    trigger = SustainedLoopbackVadTrigger()
    wiring = DetectionServerWiring(
        hub,
        is_capture_active=lambda: False,
        service=_inert_detection_service(lambda d: None, trigger),
        vad_trigger=trigger,
    )
    wiring.feed_vad_sample(0.0, 0.95)
    wiring.feed_vad_sample(1.0, 0.95)
    # Delegation reached the real trigger: sustained speech-time accumulated.
    assert trigger.speech_seconds_in_window > 0.0


def test_on_decision_drops_an_unmappable_decision(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hub = EventBroadcastHub()
    trigger = SustainedLoopbackVadTrigger()
    wiring = DetectionServerWiring(
        hub,
        is_capture_active=lambda: False,
        service=_inert_detection_service(lambda d: None, trigger),
        vad_trigger=trigger,
    )
    with caplog.at_level(logging.ERROR, logger="engine.wiring.detection_server_wiring"):
        wiring._on_decision(object())  # type: ignore[arg-type]  # no wire shape invented
    assert "unmappable detection decision" in caplog.text


# ------------------------------------------------------ live-answers spotter


class _RaisingSpotter:
    """A spotter whose every pass fails — the worker must survive both."""

    def __init__(self) -> None:
        self.segments = 0
        self.flushed = False

    async def on_final_segment(self, stream: str, text: str) -> None:
        self.segments += 1
        raise RuntimeError("segment pass exploded")

    async def flush(self) -> None:
        self.flushed = True
        raise RuntimeError("flush pass exploded")


async def test_default_spotter_factory_builds_a_spotter(
    tmp_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spotter_mod, "build_provider_clients", lambda store: {})
    monkeypatch.setattr(spotter_mod, "ProviderKeyStore", lambda: object())
    await apply_migrations(tmp_db_path, MIGRATIONS)
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        hub = EventBroadcastHub()
        wiring = LiveAnswersSpotterWiring(hub, tmp_db_path, MIGRATIONS)

        async def emit(hit: object) -> None:
            return None

        spotter = wiring._default_factory(connection, emit)  # type: ignore[arg-type]
        assert hasattr(spotter, "on_final_segment") and hasattr(spotter, "flush")
    finally:
        await connection.close()
    await wiring.shutdown()


async def test_spotter_wiring_ignores_non_event_envelopes(tmp_db_path: Path) -> None:
    hub = EventBroadcastHub()
    wiring = LiveAnswersSpotterWiring(hub, tmp_db_path, MIGRATIONS)
    await wiring._on_event(_cmd("anything", {}))
    assert wiring._queue is None  # no session started
    await wiring.shutdown()


async def test_spotter_wiring_swallows_a_session_start_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    hub = EventBroadcastHub()
    # db_path is a DIRECTORY: opening the SQLite connection fails, so the
    # session cannot start — the subscriber must swallow it, never raise.
    wiring = LiveAnswersSpotterWiring(hub, tmp_path, MIGRATIONS)
    with caplog.at_level(logging.ERROR, logger="engine.wiring.live_answers_spotter_wiring"):
        await wiring._on_event(_event(EVENT_CAPTURE_STARTED, {}))  # must NOT raise
    assert "live answers wiring failed" in caplog.text
    assert wiring._queue is None  # session never came up
    await wiring.shutdown()


async def test_spotter_worker_survives_segment_and_flush_failures(
    tmp_db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    spotter = _RaisingSpotter()
    hub = EventBroadcastHub()
    wiring = LiveAnswersSpotterWiring(
        hub, tmp_db_path, MIGRATIONS, spotter_factory=lambda conn, emit: spotter
    )
    with caplog.at_level(logging.ERROR, logger="engine.wiring.live_answers_spotter_wiring"):
        await wiring._on_event(_event(EVENT_CAPTURE_STARTED, {}))
        await wiring._on_event(_event(EVENT_TRANSCRIPT_FINAL, {"stream": "mic", "text": "hello"}))
        await wiring._on_event(_event(EVENT_CAPTURE_STOPPED, {}))
        for _ in range(200):
            await asyncio.sleep(0)
            if spotter.flushed:
                break
    # The worker invoked both passes and survived both faults (no meeting-killer).
    assert spotter.segments == 1
    assert spotter.flushed is True
    await wiring.shutdown()


# -------------------------------------------------- dictation finalizer wiring


async def test_build_finalizer_with_a_configured_vault(
    tmp_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dictation_mod, "build_provider_clients", lambda store: {})
    monkeypatch.setattr(dictation_mod, "ProviderKeyStore", lambda: object())
    monkeypatch.setenv("OMNI_VAULT_DIR", str(tmp_path))
    await apply_migrations(tmp_db_path, MIGRATIONS)
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        gateway = DictationCommandGateway(hub=EventBroadcastHub(), db_path=tmp_db_path, migrations_dir=MIGRATIONS)
        finalizer = gateway._build_finalizer(connection)
        assert isinstance(finalizer, DictationReleaseFinalizer)
    finally:
        await connection.close()


async def test_build_finalizer_without_a_vault_degrades_to_no_indexer(
    tmp_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dictation_mod, "build_provider_clients", lambda store: {})
    monkeypatch.setattr(dictation_mod, "ProviderKeyStore", lambda: object())
    monkeypatch.delenv("OMNI_VAULT_DIR", raising=False)
    await apply_migrations(tmp_db_path, MIGRATIONS)
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        gateway = DictationCommandGateway(hub=EventBroadcastHub(), db_path=tmp_db_path, migrations_dir=MIGRATIONS)
        # No configured vault: construction still succeeds (command/inject work).
        finalizer = gateway._build_finalizer(connection)
        assert isinstance(finalizer, DictationReleaseFinalizer)
    finally:
        await connection.close()


async def test_dictation_broadcast_partial_emits_the_pinned_event(
    tmp_db_path: Path,
) -> None:
    hub = EventBroadcastHub()
    events = _event_sink(hub)
    gateway = DictationCommandGateway(hub=hub, db_path=tmp_db_path, migrations_dir=MIGRATIONS)
    await gateway._broadcast_partial("live text so far")
    partials = [e for e in events if e.name == "dictation.partial"]
    assert partials and partials[0].payload["text"] == "live text so far"


# ------------------------------------------------------ provider-key custody


class _RaisingKeyStore(ProviderKeyStore):
    def set_key(self, provider: str, key: SecretApiKey) -> None:
        raise RuntimeError("DPAPI store unavailable")


async def test_keys_save_failure_reports_a_generic_error_only() -> None:
    """A save failure must never echo key-adjacent text (deny by default)."""
    gateway = ProviderKeysCommandGateway(key_store=_RaisingKeyStore())
    sent, send = _collector()
    await dispatch_keys_command(_cmd("keys.save", {"provider": "groq", "key": "abcd1234"}), gateway, send)
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "keys_error"
    assert sent[0].payload["message"] == "the key could not be saved"


async def test_keys_validate_failure_reports_a_generic_error_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(provider: str, store: object) -> object:
        raise RuntimeError("network")

    monkeypatch.setattr(keys_mod, "validate_provider_key", boom)
    gateway = ProviderKeysCommandGateway()
    sent, send = _collector()
    await dispatch_keys_command(_cmd("keys.validate", {"provider": "groq"}), gateway, send)
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "keys_error"
    assert sent[0].payload["message"] == "the key could not be validated"
