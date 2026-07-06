"""Global egress kill switch: one flag that halts ALL external model calls.

Purpose: a single, unmissable control (claude.md §5.6 project binding) that,
when engaged, makes the router refuse every external call. Capture,
transcription, and vault features do not route through this module and stay
fully functional — the switch fails closed on EGRESS, never on the user's
own local data.
Pipeline position: consulted by ``engine.router.fallback_executor`` before
any provider client is invoked. Nothing else may bypass it because the
router is the only egress path in the engine.

Security invariants:
- FAIL CLOSED: an unrecognisable value in ``OMNI_KILL_SWITCH`` counts as
  ENGAGED — ambiguity refuses egress rather than permitting it.
- The runtime override (set from the UI via the engine protocol) beats the
  environment, so the user can halt egress instantly without a restart.
"""

import os

# Environment flag: OMNI_KILL_SWITCH=1 engages the switch at process start.
KILL_SWITCH_ENV_VAR = "OMNI_KILL_SWITCH"

# Values that explicitly mean "switch off". ANYTHING else set in the env var
# (including typos like "yes please" or "trueish") counts as ENGAGED —
# deny-by-default on the security control itself.
_DISENGAGED_VALUES = frozenset({"", "0", "false", "no", "off"})
_ENGAGED_VALUES = frozenset({"1", "true", "yes", "on"})

# Runtime override set by the UI at runtime; None means "defer to the env".
_runtime_override: bool | None = None


def set_kill_switch_runtime_override(engaged: bool | None) -> None:
    """Engage/disengage the switch at runtime; ``None`` reverts to the env flag.

    The UI's Settings screen calls this through the engine protocol so the
    user can cut all egress mid-meeting without restarting the sidecar.
    """
    global _runtime_override
    _runtime_override = engaged


def kill_switch_engaged() -> bool:
    """Is egress currently forbidden? Routers MUST check this before any call.

    Resolution order: runtime override (if set) > environment flag.
    Fail closed: unknown env values engage the switch.
    """
    if _runtime_override is not None:
        return _runtime_override
    raw_value = os.environ.get(KILL_SWITCH_ENV_VAR, "").strip().lower()
    # Only explicit "off" values disengage. Recognised "on" values AND
    # anything unrecognised both engage the switch: a garbled security flag
    # must never silently permit egress (fail closed). _ENGAGED_VALUES is
    # documentation of the intended spellings; behaviour is deny-by-default.
    return raw_value not in _DISENGAGED_VALUES
