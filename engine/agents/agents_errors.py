"""Typed errors for the M4 agents layer (approval cards + tools + executor).

Purpose: every failure on the approval/execution path is a NAMED, plain-voice
error — callers branch on types, the UI shows ``str(error)`` verbatim, and
nothing degrades into a bare exception with a stack trace in the user's face.
Pipeline position: raised by ``approval_card_builder``, ``tool_registry``,
and ``card_executor``; caught at the (deferred) server wiring boundary.

Security invariant: messages never contain key material or raw provider
responses — only card ids, statuses, and human-readable reasons.
"""


class AgentsError(Exception):
    """Base class for every typed agents-layer failure."""


class CardPayloadInvalidError(AgentsError):
    """A card's stored payload does not validate against its typed model.

    Fail closed: an invalid payload is never "best-effort" executed.
    """

    def __init__(self, card_type: str, reason: str) -> None:
        self.card_type = card_type
        self.reason = reason
        super().__init__(f"card payload for '{card_type}' is invalid: {reason}")


class UnknownCardTypeError(AgentsError):
    """A card type with no registered tool (deny by default: no tool, no run)."""

    def __init__(self, card_type: str) -> None:
        self.card_type = card_type
        super().__init__(f"no tool is registered for card type '{card_type}'")


class CardNotExecutableError(AgentsError):
    """The card was not in 'approved' when execution tried to claim it.

    This is the TOCTOU defence surfacing honestly: either the card was never
    approved, or another executor claimed it first — in both cases this
    executor must do nothing (approval-before-execute, exactly-once).
    """

    def __init__(self, card_id: int, status: str | None) -> None:
        self.card_id = card_id
        self.status = status
        described = "missing" if status is None else f"in status '{status}'"
        super().__init__(
            f"card {card_id} is {described}, not 'approved' — execution refused"
        )


class ToolExecutionError(AgentsError):
    """A tool ran and failed; the message is the plain-voice reason."""

    def __init__(self, tool_name: str, reason: str) -> None:
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"{tool_name} failed: {reason}")
