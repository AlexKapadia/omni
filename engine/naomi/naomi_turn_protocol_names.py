"""Naomi turn-loop wire shapes: command payloads, event names, builders.

Purpose: the ADDITIVE naomi turn surface on WS protocol v1 — the single
source of truth the UI mirrors (apps/ui/src/naomi/naomi-turn-protocol.ts).

Commands (UI → engine):
- ``naomi.listen.start`` {open_mic?: bool} — open the mic loop. open_mic
  true keeps listening after each turn (VAD-gated conversation); false is
  push-to-talk (one utterance, mic closes on stop).
- ``naomi.listen.stop``  {flush?: bool} — close the mic. flush true forces
  the endpoint (push-to-talk release: pending speech becomes the turn);
  false discards pending audio and returns to idle.

Events (engine → UI):
- ``naomi.state``          {state: idle|listening|thinking|speaking, turn_id?}
- ``naomi.user_utterance`` {turn_id, text}                (verbatim STT)
- ``naomi.reply``          {turn_id, text, affect?, citations[], no_answer,
                            action_card_id?}
- ``naomi.turn.latency``   {turn_id, endpoint_ms, retrieval_ms, llm_ms,
                            ttfa_ms, total_ms}            (speed showcase)
- ``naomi.turn.error``     {message, turn_id?}            (honest failures)
Audio keeps riding the existing ``naomi.audio.*`` events (engine.voice).

Security invariant: command payloads are untrusted input — pydantic strict
models with extra="forbid" (deny by default); event text fields are bounded
before broadcast.
"""

from pydantic import BaseModel, ConfigDict

from engine.ask.ask_answer_contracts import AskCitation

COMMAND_NAOMI_LISTEN_START = "naomi.listen.start"
COMMAND_NAOMI_LISTEN_STOP = "naomi.listen.stop"
EVENT_NAOMI_STATE = "naomi.state"
EVENT_NAOMI_USER_UTTERANCE = "naomi.user_utterance"
EVENT_NAOMI_REPLY = "naomi.reply"
EVENT_NAOMI_TURN_LATENCY = "naomi.turn.latency"
EVENT_NAOMI_TURN_ERROR = "naomi.turn.error"

# Bound reflected error text (never stream unbounded provider output).
_MAX_ERROR_DETAIL_CHARS = 300


class NaomiListenStartPayload(BaseModel):
    """naomi.listen.start — only the open_mic flag; extras rejected."""

    model_config = ConfigDict(extra="forbid")

    open_mic: bool = False


class NaomiListenStopPayload(BaseModel):
    """naomi.listen.stop — only the flush flag; extras rejected."""

    model_config = ConfigDict(extra="forbid")

    flush: bool = False


def build_naomi_state_payload(state: str, turn_id: str | None = None) -> dict[str, object]:
    """The state event the pool + captions key off (brief §2 affect map)."""
    payload: dict[str, object] = {"state": state}
    if turn_id is not None:
        payload["turn_id"] = turn_id
    return payload


def build_naomi_user_utterance_payload(turn_id: str, text: str) -> dict[str, object]:
    """Verbatim user utterance (fidelity mandate: never rewritten)."""
    return {"turn_id": turn_id, "text": text}


def build_naomi_reply_payload(
    turn_id: str,
    text: str,
    affect: tuple[float, float, str | None] | None,
    citations: tuple[AskCitation, ...],
    no_answer: bool,
    action_card_id: int | None,
) -> dict[str, object]:
    """Naomi's reply: spoken text (tag- and marker-free), affect triple,
    exact citations for the chips, and the approval card id when the turn
    prepared an action (suggest-only — the card still needs approval)."""
    payload: dict[str, object] = {
        "turn_id": turn_id,
        "text": text,
        "no_answer": no_answer,
        "citations": [
            {
                "n": citation.n,
                "note_path": citation.note_path,
                "line_start": citation.line_start,
                "line_end": citation.line_end,
                "heading_path": citation.heading_path,
                "quote": citation.quote,
            }
            for citation in citations
        ],
    }
    if affect is not None:
        valence, arousal, burst = affect
        affect_payload: dict[str, object] = {"v": valence, "a": arousal}
        if burst is not None:
            affect_payload["burst"] = burst
        payload["affect"] = affect_payload
    if action_card_id is not None:
        payload["action_card_id"] = action_card_id
    return payload


def build_naomi_turn_error_payload(message: str, turn_id: str | None = None) -> dict[str, object]:
    """Honest failure surface; message is bounded, never key-bearing (the
    raisers redact before this point)."""
    payload: dict[str, object] = {"message": message[:_MAX_ERROR_DETAIL_CHARS]}
    if turn_id is not None:
        payload["turn_id"] = turn_id
    return payload
