"""Dictation WS command/event surface — names + typed payload builders.

Purpose: the PINNED protocol-v1 additions for dictation, documented here
so the orchestrator can wire them into ``engine/server.py`` /
``websocket_connection_handler.py`` at reconciliation WITHOUT touching M2's
files from this lane. The pill UI mirrors these names in
``apps/ui/src/pill/dictation-events-protocol.ts``.

DEFERRED WIRING SPEC (orchestrator: implement exactly this):
- command ``dictation.begin`` {mode_hint?: "note"|"command"} ->
  ``DictationSessionService.begin()``; reply payload {} on success.
  mode_hint is advisory UI state only — the engine's mode split on release
  is authoritative; the service ignores it.
- command ``dictation.end`` {} -> ``DictationSessionService.end()`` ->
  ``DictationReleaseFinalizer.finalize(text)`` -> broadcast
  ``dictation.final`` (payload built here); reply {} acknowledges.
- event ``dictation.partial`` {text}: emitted live from the session's
  ``on_partial_text`` callback (wire it to the broadcast hub).
- event ``dictation.error`` {reason}: emitted when begin/end/finalize
  raises; reason is the plain-voice exception message (already redacted —
  router errors scrub keys at the client boundary).

Fidelity invariant: ``text`` in every payload is the verbatim transcript.
"""

from engine.dictation.dictation_finalization import DictationFinalResult
from engine.dictation.dictation_mode_splitter import DictationMode

# --- message names (pinned, dot-namespaced like "capture.start") ---
DICTATION_BEGIN_COMMAND_NAME = "dictation.begin"
DICTATION_END_COMMAND_NAME = "dictation.end"
DICTATION_PARTIAL_EVENT_NAME = "dictation.partial"
DICTATION_FINAL_EVENT_NAME = "dictation.final"
DICTATION_ERROR_EVENT_NAME = "dictation.error"


def build_dictation_partial_payload(text: str) -> dict[str, object]:
    """{text}: the verbatim transcript-so-far for the live pill."""
    return {"text": text}


def build_dictation_final_payload(result: DictationFinalResult) -> dict[str, object]:
    """The full release outcome, honestly labelled.

    Shape (pinned):
      mode: "note" | "command"
      text: verbatim transcript
      note_path / note_title / title_source: present in note mode (path is
        absolute; the pill builds its obsidian:// URI from note_title)
      intent: {intent_type, fields, confidence} present in command mode —
        RECORDED only, never executed (approval-before-execute)
      degraded_reason: honest partial-failure note, or absent
    """
    payload: dict[str, object] = {"mode": result.mode.value, "text": result.text}
    if result.mode is DictationMode.NOTE:
        if result.note_path is not None:
            payload["note_path"] = result.note_path
        if result.note_title is not None:
            payload["note_title"] = result.note_title
        if result.title_source is not None:
            payload["title_source"] = result.title_source
    if result.intent is not None:
        payload["intent"] = {
            "intent_type": result.intent.intent_type.value,
            "fields": dict(result.intent.fields),
            "confidence": result.intent.confidence,
        }
    if result.degraded_reason is not None:
        payload["degraded_reason"] = result.degraded_reason
    return payload


def build_dictation_error_payload(reason: str) -> dict[str, object]:
    """{reason}: plain-voice failure the pill can show honestly."""
    return {"reason": reason}
