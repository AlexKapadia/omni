"""Protocol v1 payloads for the M7 settings + setup-status command surface.

Purpose: pinned names and strict payload models for ``settings.get``,
``settings.update`` and ``setup.status`` — the onboarding wizard and the
Settings screen speak exactly these shapes.
Pipeline position: consumed by ``engine.wiring.app_settings_command_dispatcher``
(validation) and the UI (shape contract).

Security invariant: payloads are untrusted input — ``extra="forbid"``
everywhere, value validation happens per-key in the settings gateway
(deny by default on unknown keys and malformed values).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

COMMAND_SETTINGS_GET = "settings.get"
COMMAND_SETTINGS_UPDATE = "settings.update"
COMMAND_SETUP_STATUS = "setup.status"

# Cap on one update batch: settings are a handful of knobs, not bulk data.
_MAX_UPDATE_KEYS = 16


class SettingsGetCommandPayload(BaseModel):
    """``settings.get`` takes no arguments; extras are rejected."""

    model_config = ConfigDict(extra="forbid")


class SettingsUpdateCommandPayload(BaseModel):
    """``settings.update`` carries a non-empty ``values`` map.

    Keys/values are validated per-setting by the gateway (this model only
    pins the envelope shape; the closed key set lives with the repository).
    """

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(min_length=1, max_length=_MAX_UPDATE_KEYS)


class SetupStatusCommandPayload(BaseModel):
    """``setup.status`` takes no arguments; extras are rejected."""

    model_config = ConfigDict(extra="forbid")
