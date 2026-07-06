"""Omni ask layer — Ask-Omni answers and the live mid-meeting answer spotter.

Purpose: M3's read side over the index layer. Two services:
- :class:`AskOmniAnswerService` — one question in, one grounded answer out:
  structured-first routing, chat-tier hybrid RRF retrieval (graph expansion
  on), then synthesis through the tri-provider router (task
  ``ask_synthesis``) with inline ``[n]`` citation markers mapped exactly to
  the retrieved chunks. Empty/weak retrieval NEVER reaches a provider — the
  service answers "I don't have that in your notes." honestly instead.
- :class:`LiveAnswersSpotter` — consumes finalised transcript segments,
  spots questions on a ~20 s cadence via router task ``live_extraction``
  (JSON schema constrained), answers each with LIVE-tier retrieval only
  (top hits, no rerank, no synthesis — the <2 s budget), and emits typed
  :class:`LiveAnswerHit` events through a callback.

Pipeline position: consumes ``engine.index`` (retrieval) and
``engine.router`` (egress); consumed by the WS server layer.

SERVER WIRING (DEFERRED — the orchestrator wires at reconciliation):
- Command ``ask.query`` ``{"query": str}`` -> reply ``ask.answer`` with
  payload :func:`ask_answer_to_payload` (shape below). The handler builds
  one :class:`AskOmniAnswerService` over the app's aiosqlite connection,
  retriever, and router, then ``await service.answer(query)``.
- Event ``answers.hit`` with payload :func:`answer_hit_to_payload`,
  broadcast whenever the spotter's emit callback fires. The wiring feeds
  ``LiveAnswersSpotter.on_final_segment(stream, text)`` from every
  finalised transcript segment and calls ``flush()`` at meeting end.

Payload shapes (pinned; the UI parses these fail-closed):
``ask.answer``: ``{"headline": str, "answer_md": str, "no_answer": bool,
"citations": [{"n": int, "note_path": str, "line_start": int,
"line_end": int, "heading_path": str, "quote": str}],
"latency": {"retrieval_ms": int, "synthesis_ms": int, "total_ms": int}}``
``answers.hit``: ``{"question": str, "asked_by": str,
"spotted_to_hit_ms": int, "hits": [{"note_path": str, "line_start": int,
"line_end": int, "heading_path": str, "snippet": str, "score": float}]}``

Security invariants upheld package-wide:
- Query text and transcript text are UNTRUSTED DATA: they travel only in
  the router's ``messages`` data channel, never in ``system_frame``.
- Fail honest: no retrieved context above the floor means no provider
  call and an explicit "I don't have that in your notes." — never a
  hallucinated answer.
- All egress goes through ``engine.router`` (kill switch + ledger apply).
"""

from engine.ask.ask_answer_contracts import (
    AskAnswer,
    AskCitation,
    AskLatencyBreakdown,
    LiveAnswerHit,
    LiveAnswerSource,
    answer_hit_to_payload,
    ask_answer_to_payload,
)
from engine.ask.ask_omni_answer_service import AskOmniAnswerService
from engine.ask.ask_prompt_frames import NO_ANSWER_TEXT
from engine.ask.live_answers_spotter import LiveAnswersSpotter
from engine.ask.structured_first_retrieval import (
    MINIMUM_HYBRID_RRF_SCORE,
    StructuredFirstResult,
    retrieve_structured_first,
)

ASK_QUERY_COMMAND_NAME = "ask.query"  # deferred wiring: see module docstring
ASK_ANSWER_REPLY_NAME = "ask.answer"
ANSWERS_HIT_EVENT_NAME = "answers.hit"

__all__ = [
    "ANSWERS_HIT_EVENT_NAME",
    "ASK_ANSWER_REPLY_NAME",
    "ASK_QUERY_COMMAND_NAME",
    "MINIMUM_HYBRID_RRF_SCORE",
    "NO_ANSWER_TEXT",
    "AskAnswer",
    "AskCitation",
    "AskLatencyBreakdown",
    "AskOmniAnswerService",
    "LiveAnswerHit",
    "LiveAnswerSource",
    "LiveAnswersSpotter",
    "StructuredFirstResult",
    "answer_hit_to_payload",
    "ask_answer_to_payload",
    "retrieve_structured_first",
]
