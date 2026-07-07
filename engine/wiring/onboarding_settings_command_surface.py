"""Builds and owns the M7 onboarding/settings command surface as one unit.

Purpose: keep ``engine.server`` pure routing/lifecycle by grouping the five
command-driven M7 gateways (settings, provider keys, router ledger, model
download, Google connect) behind one holder — built from the same
factory-or-default seam the rest of the server uses, with a single boot hook
and a single shutdown. Construction is inert (no keys, no I/O, no network):
each gateway resolves its dependencies per command, so a missing dependency
refuses THAT command honestly, never engine boot.
Pipeline position: assembled by ``engine.server.create_app``; the handler
reads the gateways off it to dispatch the M7 command names.

Security invariant: the boot hook makes a user-engaged kill switch and a
chosen vault survive restarts (fail closed on egress across reboots);
shutdown cancels any in-flight download / OAuth flow so no background task
outlives the process.
"""

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from engine.protocol import Envelope, EventBroadcastHub
from engine.wiring.app_settings_command_dispatcher import (
    SETTINGS_COMMAND_NAMES,
    dispatch_settings_command,
)
from engine.wiring.app_settings_command_gateway import AppSettingsCommandGateway
from engine.wiring.google_connect_command_dispatcher import (
    GOOGLE_COMMAND_NAMES,
    GoogleConnectCommandGateway,
    dispatch_google_command,
)
from engine.wiring.ledger_summary_command_dispatcher import (
    LEDGER_COMMAND_NAMES,
    LedgerSummaryCommandGateway,
    dispatch_ledger_command,
)
from engine.wiring.models_download_command_dispatcher import (
    MODELS_COMMAND_NAMES,
    ModelsDownloadCommandGateway,
    dispatch_models_command,
)
from engine.wiring.provider_keys_command_dispatcher import (
    KEYS_COMMAND_NAMES,
    ProviderKeysCommandGateway,
    dispatch_keys_command,
)
from engine.wiring.server_default_service_factories import (
    default_google_gateway_factory,
    default_keys_gateway_factory,
    default_ledger_gateway_factory,
    default_models_gateway_factory,
    default_settings_gateway_factory,
)

# Every command name the M7 surface owns — the handler routes exactly these
# here in one branch (deny by default on everything else).
M7_COMMAND_NAMES = (
    SETTINGS_COMMAND_NAMES
    | KEYS_COMMAND_NAMES
    | LEDGER_COMMAND_NAMES
    | MODELS_COMMAND_NAMES
    | GOOGLE_COMMAND_NAMES
)

# Factory seams (a factory, not an instance, so gateways build AFTER settings
# load, against the hub the app owns; tests inject fakes here).
SettingsGatewayFactory = Callable[[], AppSettingsCommandGateway]
KeysGatewayFactory = Callable[[], ProviderKeysCommandGateway]
LedgerGatewayFactory = Callable[[], LedgerSummaryCommandGateway]
ModelsGatewayFactory = Callable[[EventBroadcastHub], ModelsDownloadCommandGateway]
GoogleGatewayFactory = Callable[[EventBroadcastHub], GoogleConnectCommandGateway]


@dataclass(frozen=True)
class OnboardingSettingsCommandSurface:
    """The five M7 command gateways, owned as one unit."""

    settings_gateway: AppSettingsCommandGateway
    keys_gateway: ProviderKeysCommandGateway
    ledger_gateway: LedgerSummaryCommandGateway
    models_gateway: ModelsDownloadCommandGateway
    google_gateway: GoogleConnectCommandGateway

    async def apply_persisted_settings_at_boot(self) -> None:
        """Production boot hook: make persisted settings effective (fail-soft)."""
        with contextlib.suppress(Exception):
            await self.settings_gateway.apply_persisted_settings_at_boot()

    async def shutdown(self) -> None:
        """Cancel any in-flight download / OAuth flow (never outlive the process)."""
        with contextlib.suppress(Exception):
            await self.models_gateway.shutdown()
        with contextlib.suppress(Exception):
            await self.google_gateway.shutdown()


async def dispatch_m7_command(
    command: Envelope,
    surface: "OnboardingSettingsCommandSurface | None",
    send: Callable[[Envelope], Awaitable[None]],
) -> None:
    """Route one M7 command to its dispatcher.

    ``surface`` is None when the M7 surface is unwired (e.g. a hermetic test
    app): each dispatcher then refuses honestly (deny by default). The
    handler guarantees ``command.name in M7_COMMAND_NAMES`` before calling.
    """
    name = command.name
    if name in SETTINGS_COMMAND_NAMES:
        await dispatch_settings_command(
            command, surface.settings_gateway if surface else None, send
        )
    elif name in KEYS_COMMAND_NAMES:
        await dispatch_keys_command(command, surface.keys_gateway if surface else None, send)
    elif name in LEDGER_COMMAND_NAMES:
        await dispatch_ledger_command(command, surface.ledger_gateway if surface else None, send)
    elif name in MODELS_COMMAND_NAMES:
        await dispatch_models_command(command, surface.models_gateway if surface else None, send)
    elif name in GOOGLE_COMMAND_NAMES:
        await dispatch_google_command(command, surface.google_gateway if surface else None, send)


def build_onboarding_settings_command_surface(
    event_hub: EventBroadcastHub,
    *,
    settings_gateway_factory: SettingsGatewayFactory | None = None,
    keys_gateway_factory: KeysGatewayFactory | None = None,
    ledger_gateway_factory: LedgerGatewayFactory | None = None,
    models_gateway_factory: ModelsGatewayFactory | None = None,
    google_gateway_factory: GoogleGatewayFactory | None = None,
) -> OnboardingSettingsCommandSurface:
    """Build the surface from the factory-or-default seam (all command-driven)."""
    return OnboardingSettingsCommandSurface(
        settings_gateway=(settings_gateway_factory or default_settings_gateway_factory)(),
        keys_gateway=(keys_gateway_factory or default_keys_gateway_factory)(),
        ledger_gateway=(ledger_gateway_factory or default_ledger_gateway_factory)(),
        models_gateway=(models_gateway_factory or default_models_gateway_factory)(event_hub),
        google_gateway=(google_gateway_factory or default_google_gateway_factory)(event_hub),
    )
