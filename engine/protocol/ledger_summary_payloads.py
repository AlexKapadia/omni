"""Protocol v1 payload for the M7 router-ledger summary command.

Purpose: pinned name and strict payload model for ``ledger.summary`` — the
Settings screen's real cost/latency view (speed is a showcase feature).
Pipeline position: consumed by
``engine.wiring.ledger_summary_command_dispatcher`` and the UI.

Correctness invariant: every cost in the reply is an EXACT decimal STRING
(summed engine-side in ``Decimal``); the UI renders the strings verbatim —
float arithmetic never touches the money path (claude.md §3.11).
"""

from pydantic import BaseModel, ConfigDict, Field

COMMAND_LEDGER_SUMMARY = "ledger.summary"

# Bounds on the recent-entries window: enough for a live feed, small enough
# that a hostile frame cannot request an unbounded read.
_MIN_LIMIT = 1
_MAX_LIMIT = 200
DEFAULT_RECENT_ENTRIES_LIMIT = 20


class LedgerSummaryCommandPayload(BaseModel):
    """``ledger.summary`` — optional ``limit`` for the recent-calls feed."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=DEFAULT_RECENT_ENTRIES_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT)
