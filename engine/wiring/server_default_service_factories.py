"""Production default factories for every service ``engine.server`` wires.

Purpose: the one place the REAL engine services are built from validated
settings — capture, finalization, the ask/dictation/approval gateways, and
the event-driven wirings (detection, live-answers spotter, approval-card
building, vault watchdog). ``create_app`` uses these when a test does not
inject a fake; ``build_uvicorn_config`` passes the production-only ones
explicitly. Split out of ``engine.server`` so the server module stays pure
routing/lifecycle.

Security invariants:
- Every factory loads settings fail-closed (bad env aborts, never guesses).
- Construction is inert: keys, the vault, and Google resolve per call, so
  a missing dependency refuses THAT action honestly, never engine boot.
"""

from pathlib import Path

from engine.ask.ask_query_command_dispatcher import AskAnswerGateway
from engine.enhance import MeetingFinalizationService
from engine.protocol import EventBroadcastHub
from engine.runtime_settings import load_engine_settings
from engine.stt.live_capture_service import LiveCaptureService
from engine.vault import VaultWriteError, resolve_vault_root
from engine.wiring.app_settings_command_gateway import AppSettingsCommandGateway
from engine.wiring.approval_card_build_server_wiring import ApprovalCardBuildWiring
from engine.wiring.approval_cards_gateway import ApprovalCardsGateway
from engine.wiring.detection_server_wiring import DetectionServerWiring
from engine.wiring.dictation_command_dispatcher import DictationCommandGateway
from engine.wiring.google_connect_command_dispatcher import GoogleConnectCommandGateway
from engine.wiring.ledger_summary_command_dispatcher import LedgerSummaryCommandGateway
from engine.wiring.live_answers_spotter_wiring import LiveAnswersSpotterWiring
from engine.wiring.models_download_command_dispatcher import ModelsDownloadCommandGateway
from engine.wiring.provider_keys_command_dispatcher import ProviderKeysCommandGateway
from engine.wiring.vault_watchdog_server_wiring import VaultWatchdogServerWiring

# The repo's migrations directory (packaging bundles it next to the engine).
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def default_capture_service_factory(hub: EventBroadcastHub) -> LiveCaptureService:
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    return LiveCaptureService(db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR, hub=hub)


def default_finalization_service_factory(hub: EventBroadcastHub) -> MeetingFinalizationService:
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    # Construction is inert (no keys, no I/O): providers/vault resolve per
    # finalize call, so a missing key refuses that call, never engine boot.
    return MeetingFinalizationService(
        db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR, hub=hub
    )


def default_ask_gateway_factory() -> AskAnswerGateway:
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    return AskAnswerGateway(db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR)


def default_dictation_gateway_factory(hub: EventBroadcastHub) -> DictationCommandGateway:
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    return DictationCommandGateway(hub=hub, db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR)


def default_approval_gateway_factory(hub: EventBroadcastHub) -> ApprovalCardsGateway:
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    # Construction is inert: registry/session/router resolve per command,
    # so a missing vault or Google account refuses THAT card, never boot.
    return ApprovalCardsGateway(hub=hub, db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR)


def default_settings_gateway_factory() -> AppSettingsCommandGateway:
    """Real app-settings gateway over the settings database; command-driven.

    Construction is inert (no keys, no I/O): the key store, models directory,
    and Google store all resolve per command, so a missing dependency refuses
    THAT command honestly, never engine boot.
    """
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    return AppSettingsCommandGateway(db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR)


def default_keys_gateway_factory() -> ProviderKeysCommandGateway:
    """Real provider-key custody gateway (DPAPI store); command-driven, inert."""
    return ProviderKeysCommandGateway()


def default_ledger_gateway_factory() -> LedgerSummaryCommandGateway:
    """Real router-ledger summary gateway over the settings database."""
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    return LedgerSummaryCommandGateway(db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR)


def default_models_gateway_factory(hub: EventBroadcastHub) -> ModelsDownloadCommandGateway:
    """Real model-download gateway (pinned HTTPS sources); construction inert."""
    return ModelsDownloadCommandGateway(hub=hub)


def default_google_gateway_factory(hub: EventBroadcastHub) -> GoogleConnectCommandGateway:
    """Real Google-connect gateway (desktop OAuth flow); construction inert."""
    return GoogleConnectCommandGateway(hub=hub)


def default_card_build_wiring_factory(hub: EventBroadcastHub) -> ApprovalCardBuildWiring:
    """Real card-building seams over the settings database; production only."""
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    return ApprovalCardBuildWiring(hub, db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR)


def default_vault_watchdog_factory() -> VaultWatchdogServerWiring:
    """Real vault file watcher; production only. An unconfigured vault
    yields a wiring that logs one honest OFF line instead of watching."""
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    try:
        vault_root: Path | None = resolve_vault_root()
    except VaultWriteError:
        vault_root = None  # OMNI_VAULT_DIR unset/invalid: watcher stays off
    return VaultWatchdogServerWiring(
        db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR, vault_root=vault_root
    )


def default_detection_wiring_factory(
    hub: EventBroadcastHub, capture_service: LiveCaptureService
) -> DetectionServerWiring:
    """Real probes (ctypes/winreg) + deny-by-default rules; production only."""
    return DetectionServerWiring(hub, is_capture_active=lambda: capture_service.is_capturing)


def default_spotter_wiring_factory(hub: EventBroadcastHub) -> LiveAnswersSpotterWiring:
    """Real per-meeting spotter over the settings database; production only."""
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    return LiveAnswersSpotterWiring(hub, db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR)
