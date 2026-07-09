"""Ask-Omni answer service: structured-first retrieval → grounded synthesis.

Purpose: the full M3 chat pipeline behind the ``ask.query`` command —
query → deterministic route (exact SQL first) → chat-tier hybrid RRF with
graph expansion → top 5-8 chunks → synthesis via router task
``ask_synthesis`` with inline ``[n]`` markers mapped exactly onto the
retrieved chunks → typed :class:`AskAnswer` with the measured latency
breakdown (speed is a showcase feature).
Pipeline position: above ``engine.index`` and ``engine.router``; called by
the WS server wiring (deferred — see the package docstring).

Security / honesty invariants:
- FAIL HONEST: empty or below-floor retrieval returns the exact
  "I don't have that in your notes." answer with ZERO provider calls —
  the model can only ever see real context (tested).
- The query and every retrieved chunk are UNTRUSTED DATA: they travel in
  the router's ``messages`` channel; the instruction channel carries only
  the constant frame from ``ask_prompt_frames``.
- A marker the model invented (no matching chunk) is stripped before the
  answer leaves this service — citations can never point at nothing.
"""

import json
import time
from collections.abc import Callable
from datetime import date

import aiosqlite

from engine.ask.ask_answer_contracts import AskAnswer, AskLatencyBreakdown
from engine.ask.ask_prompt_frames import (
    ASK_SYNTHESIS_JSON_SCHEMA,
    ASK_SYNTHESIS_SYSTEM_FRAME,
    NO_ANSWER_TEXT,
)
from engine.ask.ask_service_protocols import (
    ChunkRetrieverProtocol,
    CompletionRouterProtocol,
)
from engine.ask.citation_marker_mapping import (
    build_numbered_context,
    citations_for_answer,
    strip_dangling_markers,
)
from engine.ask.structured_first_retrieval import retrieve_structured_first
from engine.index.hybrid_rrf_retriever import TIER_CHAT
from engine.dictation.dictation_history_repository import search_dictation_entries
from engine.storage.meetings_repository import fetch_meeting_row
from engine.storage.transcript_segments_repository import list_transcript_segment_rows
from engine.stt.speaker_voice_profile import resolve_speaker_label
from engine.router.completion_contract import ChatMessage

ASK_SYNTHESIS_TASK = "ask_synthesis"
# Top 5-8 chunks per the M3 recommendation; 8 is the synthesis context cap.
MAX_CONTEXT_CHUNKS = 8
NO_ANSWER_HEADLINE = "Not in your notes"
FALLBACK_HEADLINE = "Answer"  # only when a provider ignores the JSON schema


def parse_synthesis_output(raw_text: str) -> tuple[str, str]:
    """(headline, answer) from the model's JSON — tolerant, deterministic.

    Gemini enforces the schema natively; Groq/Anthropic follow the frame's
    schema text. A non-conforming reply degrades in a fixed order: JSON
    object with string fields wins; otherwise the whole text becomes the
    answer under a short first-line headline (≤ 80 chars) or the fallback.
    """
    try:
        decoded = json.loads(raw_text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        headline = decoded.get("headline")
        answer = decoded.get("answer")
        if isinstance(headline, str) and isinstance(answer, str) and answer.strip():
            return headline.strip() or FALLBACK_HEADLINE, answer.strip()
    text = raw_text.strip()
    first_line, _, rest = text.partition("\n")
    if rest.strip() and len(first_line.strip()) <= 80:
        return first_line.strip(), rest.strip()
    return FALLBACK_HEADLINE, text


class AskOmniAnswerService:
    """One question in, one grounded + cited + timed answer out."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        retriever: ChunkRetrieverProtocol,
        router: CompletionRouterProtocol,
        *,
        clock: Callable[[], float] = time.perf_counter,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._connection = connection
        self._retriever = retriever
        self._router = router
        self._clock = clock  # injectable: latency arithmetic is tested exactly
        self._today = today

    async def answer(
        self, query: str, meeting_id: str | None = None, scope: str = "all"
    ) -> AskAnswer:
        """Run the full chat pipeline for one query."""
        if meeting_id is not None:
            return await self._answer_meeting_scoped(query, meeting_id)
        if scope == "dictation_only":
            return await self._answer_dictation_scoped(query)
        started = self._clock()
        result = await retrieve_structured_first(
            self._connection,
            self._retriever,
            query,
            tier=TIER_CHAT,
            top_n=MAX_CONTEXT_CHUNKS,
            enable_graph_expansion=True,  # chat tier: recommendation step 3
            today=self._today,
        )
        chunks = result.chunks[:MAX_CONTEXT_CHUNKS]
        retrieval_ms = self._elapsed_ms(started)
        if not chunks:
            # FAIL HONEST: nothing above the floor — no provider call at all.
            return AskAnswer(
                headline=NO_ANSWER_HEADLINE,
                answer_md=NO_ANSWER_TEXT,
                no_answer=True,
                citations=(),
                latency=AskLatencyBreakdown(retrieval_ms=retrieval_ms, synthesis_ms=0),
            )
        synthesis_started = self._clock()
        # Data channel: numbered sources + the untrusted query, never the frame.
        user_content = (
            f"Context sources:\n\n{build_numbered_context(chunks)}\n\nQuestion: {query}"
        )
        routed = await self._router.route(
            ASK_SYNTHESIS_TASK,
            ASK_SYNTHESIS_SYSTEM_FRAME,
            (ChatMessage(role="user", content=user_content),),
            json_schema=ASK_SYNTHESIS_JSON_SCHEMA,
        )
        synthesis_ms = self._elapsed_ms(synthesis_started)
        headline, answer_text = parse_synthesis_output(routed.completion.text)
        answer_md = strip_dangling_markers(answer_text, len(chunks))
        no_answer = NO_ANSWER_TEXT in answer_md and len(answer_md) <= len(NO_ANSWER_TEXT) + 8
        if no_answer:
            # The model reported the context lacks the answer: honest verdict,
            # canonical copy, and no citations (there is nothing to cite).
            return AskAnswer(
                headline=NO_ANSWER_HEADLINE,
                answer_md=NO_ANSWER_TEXT,
                no_answer=True,
                citations=(),
                latency=AskLatencyBreakdown(
                    retrieval_ms=retrieval_ms, synthesis_ms=synthesis_ms
                ),
            )
        return AskAnswer(
            headline=headline,
            answer_md=answer_md,
            no_answer=False,
            citations=citations_for_answer(chunks, answer_md),
            latency=AskLatencyBreakdown(retrieval_ms=retrieval_ms, synthesis_ms=synthesis_ms),
        )

    async def _answer_dictation_scoped(self, query: str) -> AskAnswer:
        """Answer using dictation history entries only."""
        started = self._clock()
        entries = await search_dictation_entries(self._connection, query, limit=20)
        retrieval_ms = self._elapsed_ms(started)
        if not entries:
            return AskAnswer(
                headline=NO_ANSWER_HEADLINE,
                answer_md=NO_ANSWER_TEXT,
                no_answer=True,
                citations=(),
                latency=AskLatencyBreakdown(retrieval_ms=retrieval_ms, synthesis_ms=0),
            )
        lines = []
        for entry in entries[:12]:
            cleaned = entry.get("cleaned_text")
            raw = str(entry.get("raw_text", ""))
            body = cleaned if isinstance(cleaned, str) and cleaned.strip() else raw
            mode = entry.get("mode", "note")
            created = entry.get("created_at", "")
            lines.append(f"[{created}] ({mode}) {body}")
        context = "\n".join(lines)
        synthesis_started = self._clock()
        user_content = f"Dictation history:\n\n{context}\n\nQuestion: {query}"
        routed = await self._router.route(
            ASK_SYNTHESIS_TASK,
            ASK_SYNTHESIS_SYSTEM_FRAME,
            (ChatMessage(role="user", content=user_content),),
            json_schema=ASK_SYNTHESIS_JSON_SCHEMA,
        )
        synthesis_ms = self._elapsed_ms(synthesis_started)
        headline, answer_text = parse_synthesis_output(routed.completion.text)
        return AskAnswer(
            headline=headline,
            answer_md=strip_dangling_markers(answer_text.strip(), 0),
            no_answer=False,
            citations=(),
            latency=AskLatencyBreakdown(retrieval_ms=retrieval_ms, synthesis_ms=synthesis_ms),
        )

    async def _answer_meeting_scoped(self, query: str, meeting_id: str) -> AskAnswer:
        """Answer a question using one meeting's stored content only."""
        started = self._clock()
        row = await fetch_meeting_row(self._connection, meeting_id)
        if row is None:
            return AskAnswer(
                headline="Meeting not found",
                answer_md="That meeting does not exist.",
                no_answer=True,
                citations=(),
                latency=AskLatencyBreakdown(retrieval_ms=0, synthesis_ms=0),
            )
        segments = await list_transcript_segment_rows(self._connection, meeting_id)
        transcript_lines = [
            f"{resolve_speaker_label(s.speaker_id, 'Me')}: {s.text}" for s in segments
        ]
        context_parts = [f"Meeting title: {row.title}"]
        if row.enhanced_notes_md and row.enhanced_notes_md.strip():
            context_parts.extend(["Enhanced notes:", row.enhanced_notes_md.strip()])
        if row.notes_text and row.notes_text.strip():
            context_parts.extend(["Rough notes:", row.notes_text.strip()])
        if transcript_lines:
            context_parts.extend(["Transcript:", "\n".join(transcript_lines)])
        context = "\n\n".join(context_parts)
        retrieval_ms = self._elapsed_ms(started)
        if not context.strip():
            return AskAnswer(
                headline=NO_ANSWER_HEADLINE,
                answer_md=NO_ANSWER_TEXT,
                no_answer=True,
                citations=(),
                latency=AskLatencyBreakdown(retrieval_ms=retrieval_ms, synthesis_ms=0),
            )
        synthesis_started = self._clock()
        user_content = f"Meeting context:\n\n{context}\n\nQuestion: {query}"
        routed = await self._router.route(
            ASK_SYNTHESIS_TASK,
            ASK_SYNTHESIS_SYSTEM_FRAME,
            (ChatMessage(role="user", content=user_content),),
            json_schema=ASK_SYNTHESIS_JSON_SCHEMA,
        )
        synthesis_ms = self._elapsed_ms(synthesis_started)
        headline, answer_text = parse_synthesis_output(routed.completion.text)
        answer_md = answer_text.strip()
        no_answer = NO_ANSWER_TEXT in answer_md and len(answer_md) <= len(NO_ANSWER_TEXT) + 8
        return AskAnswer(
            headline=headline if not no_answer else NO_ANSWER_HEADLINE,
            answer_md=NO_ANSWER_TEXT if no_answer else answer_md,
            no_answer=no_answer,
            citations=(),
            latency=AskLatencyBreakdown(retrieval_ms=retrieval_ms, synthesis_ms=synthesis_ms),
        )

    def _elapsed_ms(self, since: float) -> int:
        """Whole milliseconds, rounded — the unit the UI renders verbatim."""
        return round((self._clock() - since) * 1000)
