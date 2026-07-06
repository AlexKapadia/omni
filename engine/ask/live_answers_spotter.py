"""Live answers spotter: transcript feed → spotted questions → instant hits.

Purpose: the M3 live tier behind the ``answers.hit`` event. Finalised
transcript segments accumulate in a window; every ~20 s of new final text
one router call (task ``live_extraction``, JSON-schema constrained) spots
the questions asked; each NEW question gets LIVE-tier retrieval only —
top hits with the weak-result floor, NO rerank and NO synthesis (the <2 s
budget) — and is emitted as a typed :class:`LiveAnswerHit` through the
callback, carrying the measured ``spotted_to_hit_ms``.
Pipeline position: fed by the server wiring (deferred) from every
finalised segment; emits toward the WS broadcast.

Resilience / honesty invariants:
- Malformed spotter output (non-JSON, wrong shapes) is TOLERATED: the
  window is consumed and nothing is emitted — never a crash mid-meeting,
  never an invented question (tested).
- Router unavailability (kill switch, chain exhausted) is tolerated the
  same way: live answering degrades to silence, capture is untouched.
- Repeated questions are deduplicated by a rolling normalised set — the
  same question asked twice in a meeting hits once.
- Transcript text is UNTRUSTED DATA: it rides the router's ``messages``
  channel only; the instruction channel is the constant spotter frame.
"""

import json
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import date

import aiosqlite

from engine.ask.ask_answer_contracts import LiveAnswerHit, LiveAnswerSource
from engine.ask.ask_prompt_frames import (
    QUESTION_SPOTTER_SYSTEM_FRAME,
    QUESTIONS_JSON_SCHEMA,
)
from engine.ask.ask_service_protocols import (
    ChunkRetrieverProtocol,
    CompletionRouterProtocol,
)
from engine.ask.citation_marker_mapping import truncate_quote
from engine.ask.structured_first_retrieval import retrieve_structured_first
from engine.index.hybrid_rrf_retriever import TIER_LIVE
from engine.router.completion_contract import ChatMessage
from engine.router.router_errors import RouterError

LIVE_EXTRACTION_TASK = "live_extraction"
DEFAULT_SPOT_CADENCE_SECONDS = 20.0
LIVE_HITS_TOP_N = 5
DEFAULT_DEDUPE_CAPACITY = 50  # rolling window of already-answered questions
_ASKED_BY_VALUES = frozenset({"me", "them"})
_NORMALISE = re.compile(r"\w+")

HitEmitter = Callable[[LiveAnswerHit], Awaitable[None]]


def normalise_question(text: str) -> str:
    """Dedupe key: lowercased word tokens only — punctuation/case immaterial."""
    return " ".join(_NORMALISE.findall(text.lower()))


def parse_spotted_questions(raw_text: str) -> list[tuple[str, str]]:
    """Tolerant parse of the spotter's JSON into (text, asked_by) pairs.

    Anything malformed — non-JSON, wrong container types, non-string or
    empty question text — contributes nothing and never raises. Unknown
    ``asked_by`` values normalise to ``"unknown"`` (honest, not guessed).
    """
    try:
        decoded = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, dict):
        return []
    questions = decoded.get("questions")
    if not isinstance(questions, list):
        return []
    parsed: list[tuple[str, str]] = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        asked_by = item.get("asked_by")
        normalised_by = asked_by if isinstance(asked_by, str) else ""
        parsed.append(
            (text.strip(), normalised_by if normalised_by in _ASKED_BY_VALUES else "unknown")
        )
    return parsed


class LiveAnswersSpotter:
    """Cadenced question spotting + live-tier retrieval over one meeting."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        retriever: ChunkRetrieverProtocol,
        router: CompletionRouterProtocol,
        emit: HitEmitter,
        *,
        cadence_seconds: float = DEFAULT_SPOT_CADENCE_SECONDS,
        dedupe_capacity: int = DEFAULT_DEDUPE_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._connection = connection
        self._retriever = retriever
        self._router = router
        self._emit = emit
        self._cadence_seconds = cadence_seconds
        self._clock = clock
        self._today = today
        self._window: list[str] = []  # new final lines since the last spot
        self._last_spot_at = clock()
        self._seen_questions: deque[str] = deque(maxlen=dedupe_capacity)

    async def on_final_segment(self, stream: str, text: str) -> None:
        """Feed one finalised segment; spot when a cadence window has filled.

        ``stream`` is the capture label ('me'/'them'); anything else is
        labelled Them (other-party text is the conservative default).
        """
        if not text.strip():
            return
        prefix = "Me" if stream == "me" else "Them"
        self._window.append(f"{prefix}: {text.strip()}")
        if self._clock() - self._last_spot_at >= self._cadence_seconds:
            await self._spot_window()

    async def flush(self) -> None:
        """Spot whatever is buffered now (wiring calls this at meeting end)."""
        if self._window:
            await self._spot_window()

    async def _spot_window(self) -> None:
        """One spotting pass: consume the window, answer each NEW question."""
        window_text = "\n".join(self._window)
        self._window.clear()
        self._last_spot_at = self._clock()
        try:
            routed = await self._router.route(
                LIVE_EXTRACTION_TASK,
                QUESTION_SPOTTER_SYSTEM_FRAME,
                (ChatMessage(role="user", content=window_text),),  # data channel
                json_schema=QUESTIONS_JSON_SCHEMA,
            )
        except RouterError:
            return  # live path degrades to silence; capture is untouched
        for question, asked_by in parse_spotted_questions(routed.completion.text):
            key = normalise_question(question)
            if not key or key in self._seen_questions:
                continue  # rolling dedupe: same question hits once
            self._seen_questions.append(key)
            await self._answer_question(question, asked_by)

    async def _answer_question(self, question: str, asked_by: str) -> None:
        """LIVE-tier retrieval for one question; emit only real hits."""
        spotted_at = self._clock()  # question detection — the <2 s budget anchor
        result = await retrieve_structured_first(
            self._connection,
            self._retriever,
            question,
            tier=TIER_LIVE,  # live tier: no rerank, no synthesis (binding)
            top_n=LIVE_HITS_TOP_N,
            enable_graph_expansion=False,  # live = route + hybrid RRF only
            today=self._today,
        )
        if not result.chunks:
            return  # honest: no hit is better than a fabricated one
        spotted_to_hit_ms = round((self._clock() - spotted_at) * 1000)
        await self._emit(
            LiveAnswerHit(
                question=question,
                asked_by=asked_by,
                spotted_to_hit_ms=spotted_to_hit_ms,
                sources=tuple(
                    LiveAnswerSource(
                        note_path=chunk.note_path,
                        line_start=chunk.line_start,
                        line_end=chunk.line_end,
                        heading_path=chunk.heading_path,
                        snippet=truncate_quote(chunk.text),
                        score=chunk.score,
                    )
                    for chunk in result.chunks
                ),
            )
        )
