"""Adversarial error/refusal paths of the approval-card and models-download wiring.

Every test asserts the EXACT fail-closed behaviour of a dispatcher/gateway
branch: an honest refusal reply, a swallowed wiring failure that never takes
the loop down, a straggler execution that gets cancelled at shutdown, and the
model-download failure/completion events. No network: the downloader is
replaced by an in-process fake, and every gateway runs over a tmp database.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from pathlib import Path

import aiosqlite
import pytest

import engine.wiring.approval_cards_gateway as gateway_mod
import engine.wiring.models_download_command_dispatcher as models_mod
from engine.dictation.dictation_finalization import DictationFinalResult
from engine.dictation.dictation_mode_splitter import DictationMode
from engine.protocol import (
    EVENT_ENHANCE_READY,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
)
from engine.router.fallback_executor import ProviderRouter
from engine.storage import apply_migrations, open_sqlite_connection
from engine.stt.model_weights_downloader import ModelIntegrityError
from engine.vault import VaultNotConfiguredError
from engine.wiring.approval_card_build_server_wiring import ApprovalCardBuildWiring
from engine.wiring.approval_cards_gateway import ApprovalCardsGateway, CardCommandRefused
from engine.wiring.approval_command_dispatcher import dispatch_approval_command
from engine.wiring.models_download_command_dispatcher import (
    ModelsDownloadCommandGateway,
    dispatch_models_command,
)
from tests.approval_card_ws_test_support import (
    NotConnectedGoogleSession,
    db_card,
    seed_pending_card,
)
from tests.conftest import REPO_ROOT

MIGRATIONS = REPO_ROOT / "migrations"
TS = "2026-07-06T12:00:00+00:00"

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


async def _sleep_forever() -> None:
    await asyncio.Event().wait()


async def _wait_all_pending(
    tasks: Iterable[asyncio.Task[None]], timeout: float | None = None
) -> tuple[set[asyncio.Task[None]], set[asyncio.Task[None]]]:
    """Test double for ``asyncio.wait``: the grace window elapses with every
    task still pending, so ``shutdown`` must fall through to cancellation."""
    return set(), set(tasks)


def _build_gateway(
    tmp_db: Path,
    vault_root: Path,
    *,
    migrations_dir: Path = MIGRATIONS,
    registry_factory: Callable[[Path | None], object] | None = None,
    vault_root_resolver: Callable[[], Path] | None = None,
) -> ApprovalCardsGateway:
    return ApprovalCardsGateway(
        hub=EventBroadcastHub(),
        db_path=tmp_db,
        migrations_dir=migrations_dir,
        registry_factory=registry_factory,  # type: ignore[arg-type]
        google_session_factory=NotConnectedGoogleSession,
        router_factory=lambda recorder: ProviderRouter({}, recorder),
        vault_root_resolver=vault_root_resolver or (lambda: vault_root),
    )


# --------------------------------------------------------- approval gateway


def test_default_router_factory_builds_a_provider_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production default wires a keyed ProviderRouter (no DPAPI in tests)."""
    monkeypatch.setattr(gateway_mod, "build_provider_clients", lambda store: {})
    monkeypatch.setattr(gateway_mod, "ProviderKeyStore", lambda: object())

    async def recorder(entry: object) -> None:
        return None

    router = gateway_mod._default_router_factory(recorder)
    assert isinstance(router, ProviderRouter)


async def test_resolve_vault_root_returns_none_when_unconfigured(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    def boom() -> Path:
        raise VaultNotConfiguredError("OMNI_VAULT_DIR is not set")

    gateway = _build_gateway(tmp_db_path, tmp_path, vault_root_resolver=boom)
    # Fail-soft: an unconfigured vault degrades to a preview-only (None) root,
    # never a crash.
    assert gateway._resolve_vault_root() is None


async def test_retry_on_unknown_card_refuses_honestly(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    gateway = _build_gateway(tmp_db_path, tmp_path)
    with pytest.raises(CardCommandRefused, match="4242 does not exist"):
        await gateway.retry(4242)


async def test_execute_card_refuses_a_non_approved_card_and_leaves_it_pending(
    tmp_db_path: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The executor claims only an 'approved' row; a pending card is refused
    (CardNotExecutableError) and the loop never crashes — exactly-once."""
    card_id = await seed_pending_card(tmp_db_path)
    gateway = _build_gateway(tmp_db_path, tmp_path)
    with caplog.at_level(logging.WARNING, logger="engine.wiring.approval_cards_gateway"):
        await gateway._execute_card(card_id)  # never raises
    status, _ = await db_card(tmp_db_path, card_id)
    assert status == "pending"  # untouched: it was never approved
    assert "refused" in caplog.text


async def test_execute_card_swallows_a_wiring_failure(
    tmp_db_path: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A registry-build failure is logged, not propagated (a wiring fault must
    never take the event loop down)."""

    def boom_registry(root: Path | None) -> object:
        raise RuntimeError("registry construction blew up")

    gateway = _build_gateway(tmp_db_path, tmp_path, registry_factory=boom_registry)
    with caplog.at_level(logging.ERROR, logger="engine.wiring.approval_cards_gateway"):
        await gateway._execute_card(1)  # never raises
    assert "execution wiring failed" in caplog.text


async def test_shutdown_cancels_a_straggler_execution(
    tmp_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _build_gateway(tmp_db_path, tmp_path)
    hanging: asyncio.Task[None] = asyncio.create_task(_sleep_forever())
    gateway._execution_tasks.add(hanging)
    monkeypatch.setattr("engine.wiring.approval_cards_gateway.asyncio.wait", _wait_all_pending)
    await gateway.shutdown()
    assert hanging.cancelled()  # the straggler was really cancelled


# ------------------------------------------------------ approval dispatcher


async def test_approval_dispatch_refuses_when_gateway_unwired() -> None:
    sent, send = _collector()
    await dispatch_approval_command(_cmd("cards.list", {}), None, send)
    assert len(sent) == 1
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "card_error"
    assert "not available" in str(sent[0].payload["message"])


async def test_approval_dispatch_reports_gateway_exception_as_card_error(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    """A non-refusal gateway failure (here: unreadable migrations) becomes a
    structured card_error, never a crashed socket."""
    gateway = _build_gateway(
        tmp_db_path, tmp_path, migrations_dir=Path("no-such-migrations-dir")
    )
    sent, send = _collector()
    await dispatch_approval_command(_cmd("card.approve", {"id": 1}), gateway, send)
    assert len(sent) == 1
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "card_error"
    assert "card.approve failed" in str(sent[0].payload["message"])


# -------------------------------------------------- card-build server wiring


class _SpawnRaisingWiring(ApprovalCardBuildWiring):
    def _spawn(self, work: Coroutine[object, object, None]) -> None:
        work.close()  # avoid an un-awaited-coroutine warning
        raise RuntimeError("spawn exploded")


class _LockedRaisingWiring(ApprovalCardBuildWiring):
    async def _build_for_meeting_locked(self, meeting_id: str) -> None:
        raise RuntimeError("locked build exploded")


async def test_build_wiring_ignores_non_event_envelopes(tmp_db_path: Path) -> None:
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, tmp_db_path, MIGRATIONS)
    await wiring._on_event(_cmd("anything", {}))
    assert not wiring._tasks  # a command is never a build trigger
    await wiring.shutdown()


async def test_build_wiring_on_event_never_raises_when_spawn_fails(
    tmp_db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    hub = EventBroadcastHub()
    wiring = _SpawnRaisingWiring(hub, tmp_db_path, MIGRATIONS)
    event = Envelope(
        v=1,
        kind=EnvelopeKind.EVENT,
        name=EVENT_ENHANCE_READY,
        id="e1",
        payload={"meeting_id": "m1"},
    )
    with caplog.at_level(logging.ERROR, logger="engine.wiring.approval_card_build_server_wiring"):
        await wiring._on_event(event)  # the hub subscriber must NEVER raise
    assert "failed handling" in caplog.text
    await wiring.shutdown()


async def test_build_for_meeting_swallows_a_build_failure(
    tmp_db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    hub = EventBroadcastHub()
    wiring = _LockedRaisingWiring(hub, tmp_db_path, MIGRATIONS)
    with caplog.at_level(logging.ERROR, logger="engine.wiring.approval_card_build_server_wiring"):
        await wiring._build_for_meeting("m1")  # suggest-only: never costs the note
    assert "building approval cards for meeting m1 failed" in caplog.text
    await wiring.shutdown()


async def test_finalized_meeting_without_extraction_builds_no_cards(
    tmp_db_path: Path,
) -> None:
    await apply_migrations(tmp_db_path, MIGRATIONS)
    connection = await aiosqlite.connect(tmp_db_path)
    try:
        await connection.execute(
            "INSERT INTO meetings (id, title, started_at, finalized_at)"
            " VALUES ('m1', 'Retro', ?, ?)",
            (TS, TS),
        )
        await connection.commit()
    finally:
        await connection.close()

    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, tmp_db_path, MIGRATIONS)
    await wiring._build_for_meeting_locked("m1")  # finalized, but no extraction row

    connection = await aiosqlite.connect(tmp_db_path)
    try:
        cursor = await connection.execute("SELECT COUNT(*) FROM approval_cards")
        row = await cursor.fetchone()
        await cursor.close()
    finally:
        await connection.close()
    assert row is not None and int(row[0]) == 0  # nothing to suggest -> no cards
    await wiring.shutdown()


async def test_on_dictation_final_with_missing_intent_builds_nothing(
    tmp_db_path: Path,
) -> None:
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, tmp_db_path, MIGRATIONS)
    result = DictationFinalResult(mode=DictationMode.COMMAND, text="do it", intent_row_id=999)
    await wiring.on_dictation_final(result)  # intent row 999 does not exist

    connection = await aiosqlite.connect(tmp_db_path)
    try:
        cursor = await connection.execute("SELECT COUNT(*) FROM approval_cards")
        row = await cursor.fetchone()
        await cursor.close()
    finally:
        await connection.close()
    assert row is not None and int(row[0]) == 0
    await wiring.shutdown()


async def test_intent_whitelist_read_error_fails_closed(tmp_db_path: Path) -> None:
    """A read failure on the whitelist means NOT whitelisted (card stays pending)."""
    await apply_migrations(tmp_db_path, MIGRATIONS)
    connection = await open_sqlite_connection(tmp_db_path)
    await connection.close()  # a closed connection makes read_setting raise
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, tmp_db_path, MIGRATIONS)
    assert await wiring._intent_is_whitelisted(connection, "note") is False
    await wiring.shutdown()


async def test_build_wiring_shutdown_cancels_a_straggler_build(
    tmp_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, tmp_db_path, MIGRATIONS)
    hanging: asyncio.Task[None] = asyncio.create_task(_sleep_forever())
    wiring._tasks.add(hanging)
    monkeypatch.setattr(
        "engine.wiring.approval_card_build_server_wiring.asyncio.wait", _wait_all_pending
    )
    await wiring.shutdown()
    assert hanging.cancelled()


# ------------------------------------------------- models-download gateway


async def _drain(gateway: ModelsDownloadCommandGateway) -> None:
    task = gateway._task
    assert task is not None
    await task


def _completed(events: list[Envelope]) -> Envelope:
    matches = [e for e in events if e.name == "models.download.completed"]
    assert matches, f"no completed event in {[e.name for e in events]}"
    return matches[0]


def _failed(events: list[Envelope]) -> Envelope:
    matches = [e for e in events if e.name == "models.download.failed"]
    assert matches, f"no failed event in {[e.name for e in events]}"
    return matches[0]


async def test_models_download_completes_ok_with_default_specs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_download(
        on_progress: object, *, models_dir: object, manifest_path: object, fetch: object
    ) -> list[dict[str, object]]:
        return [{"file": "parakeet.bin"}]

    monkeypatch.setattr(models_mod, "download_models_with_progress", fake_download)
    hub = EventBroadcastHub()
    events = _event_sink(hub)
    gateway = ModelsDownloadCommandGateway(hub)  # specs=None -> module-default path
    assert gateway.begin_download() is True
    await _drain(gateway)
    completed = _completed(events)
    assert completed.payload["ok"] is True
    assert completed.payload["files"] == [{"file": "parakeet.bin"}]


async def test_models_download_uses_explicit_specs_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_download(
        on_progress: object,
        *,
        models_dir: object,
        manifest_path: object,
        fetch: object,
        specs: object,
    ) -> list[dict[str, object]]:
        seen["specs"] = specs
        return []

    monkeypatch.setattr(models_mod, "download_models_with_progress", fake_download)
    hub = EventBroadcastHub()
    events = _event_sink(hub)
    gateway = ModelsDownloadCommandGateway(hub, specs=())  # explicit (empty) set
    assert gateway.begin_download() is True
    await _drain(gateway)
    assert seen["specs"] == ()  # the explicit-specs branch really ran
    assert _completed(events).payload["ok"] is True


async def test_models_download_reports_integrity_failure_per_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_download(
        on_progress: object, *, models_dir: object, manifest_path: object, fetch: object
    ) -> list[dict[str, object]]:
        raise ModelIntegrityError("bge-small.bin", "expected", "actual")

    monkeypatch.setattr(models_mod, "download_models_with_progress", fake_download)
    hub = EventBroadcastHub()
    events = _event_sink(hub)
    gateway = ModelsDownloadCommandGateway(hub)
    gateway.begin_download()
    await _drain(gateway)
    assert _failed(events).payload["file"] == "bge-small.bin"  # honest per-file name
    assert _completed(events).payload["ok"] is False


async def test_models_download_reports_generic_failure_without_a_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_download(
        on_progress: object, *, models_dir: object, manifest_path: object, fetch: object
    ) -> list[dict[str, object]]:
        raise RuntimeError("disk full")

    monkeypatch.setattr(models_mod, "download_models_with_progress", fake_download)
    hub = EventBroadcastHub()
    events = _event_sink(hub)
    gateway = ModelsDownloadCommandGateway(hub)
    gateway.begin_download()
    await _drain(gateway)
    failed = _failed(events)
    assert failed.payload["file"] == ""  # no filename for a non-integrity failure
    assert "download failed" in str(failed.payload["message"])
    assert _completed(events).payload["ok"] is False


async def test_models_dispatch_refuses_when_unavailable() -> None:
    sent, send = _collector()
    await dispatch_models_command(_cmd("models.download", {}), None, send)
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "unknown_command"


async def test_models_dispatch_rejects_extra_fields() -> None:
    hub = EventBroadcastHub()
    gateway = ModelsDownloadCommandGateway(hub)
    sent, send = _collector()
    # The client can never supply a URL: extra fields are denied by default.
    await dispatch_models_command(_cmd("models.download", {"url": "http://x"}), gateway, send)
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "invalid_payload"
    assert gateway.is_downloading() is False  # never started on a bad payload
