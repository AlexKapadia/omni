"""Naomi's live-tier voice answer: retrieve fast → synthesize → affect + cite.

Purpose: turns one verbatim user utterance into a spoken answer. It uses the
LIVE retrieval tier (structured-first + floored hybrid RRF, NO graph
expansion, NO rerank) so it answers in milliseconds, then a single
``ask_synthesis`` router call grounded in the retrieved chunks. It parses the
model's leading affect self-tag (driving Cartesia emotion + the pool), maps
inline ``[n]`` markers onto real chunks for the UI citation chips, and STRIPS
every marker from the spoken text so Cartesia never reads "one, two" aloud.
Pipeline position: called by ``engine.naomi.naomi_turn_orchestrator`` between
the mic session (utterance in) and the speaker (clause chunks out).

Honesty invariants (§3.11, §5.6):
- FAIL HONEST: empty / below-floor retrieval returns NO_ANSWER_TEXT with
  ZERO provider calls — the model only ever sees real context (tested).
- Grounded or nothing: markers pointing at no chunk are stripped; a spoken
  answer can never cite a source that was not retrieved.
- The utterance and every chunk are UNTRUSTED DATA (router messages channel);
  only NAOMI_VOICE_SYSTEM_FRAME rides the instruction channel.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import aiosqlite

from engine.ask.ask_answer_contracts import AskCitation
from engine.ask.ask_service_protocols import ChunkRetrieverProtocol, CompletionRouterProtocol
from engine.ask.citation_marker_mapping import (
    build_numbered_context,
    citations_for_answer,
    strip_dangling_markers,
)
from engine.ask.structured_first_retrieval import retrieve_structured_first
from engine.index.hybrid_rrf_retriever import TIER_LIVE
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.naomi.affect_self_tag_parser import ParsedAffect, parse_leading_affect_tag
from engine.naomi.naomi_turn_latency_breakdown import milliseconds_between
from engine.naomi.naomi_voice_synthesis_prompt import (
    NAOMI_NO_ANSWER_TEXT,
    NAOMI_VOICE_SYSTEM_FRAME,
)
from engine.router.completion_contract import ChatMessage

ASK_SYNTHESIS_TASK = "ask_synthesis"
# Live tier: 5 chunks is the spotter's proven fast context width — enough to
# ground one spoken answer without the chat tier's heavier top-8 + expansion.
LIVE_TOP_N = 5


@dataclass(frozen=True)
class NaomiVoiceAnswer:
    """One spoken answer: TTS-ready text, parsed affect, citations, timings."""

    spoken_text: str  # marker-free, tag-free — exactly what Cartesia speaks
    affect: ParsedAffect | None  # None ⇒ neutral fallback (tag missing/malformed)
    citations: tuple[AskCitation, ...]
    no_answer: bool
    retrieval_ms: int
    llm_ms: int


class NaomiVoiceAnswerService:
    """Utterance in → grounded, affect-tagged, cited spoken answer out."""

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

    async def answer(self, utterance: str) -> NaomiVoiceAnswer:
        """Answer one utterance. Router errors propagate typed (honest surface)."""
        retrieval_started = self._clock()
        result = await retrieve_structured_first(
            self._connection,
            self._retriever,
            utterance,
            tier=TIER_LIVE,  # ms-fast: no graph expansion, no rerank
            top_n=LIVE_TOP_N,
            enable_graph_expansion=False,
            today=self._today,
        )
        chunks = result.chunks[:LIVE_TOP_N]
        retrieval_ms = milliseconds_between(retrieval_started, self._clock())
        if not chunks:
            # FAIL HONEST: nothing above the floor — no provider call at all.
            return NaomiVoiceAnswer(
                spoken_text=NAOMI_NO_ANSWER_TEXT,
                affect=None,
                citations=(),
                no_answer=True,
                retrieval_ms=retrieval_ms,
                llm_ms=0,
            )
        synthesis_started = self._clock()
        numbered = build_numbered_context(chunks)
        user_content = f"Context sources:\n\n{numbered}\n\nQuestion: {utterance}"
        routed = await self._router.route(
            ASK_SYNTHESIS_TASK,
            NAOMI_VOICE_SYSTEM_FRAME,
            (ChatMessage(role="user", content=user_content),),
        )
        llm_ms = milliseconds_between(synthesis_started, self._clock())
        return self._assemble_answer(routed.completion.text, chunks, retrieval_ms, llm_ms)

    def _assemble_answer(
        self,
        raw_completion: str,
        chunks: list[RetrievedChunk],
        retrieval_ms: int,
        llm_ms: int,
    ) -> NaomiVoiceAnswer:
        """Parse tag, map citations, strip markers for TTS — deterministic."""
        # 1. Peel the leading affect tag off the FRONT (never reaches TTS/UI).
        affect, body = parse_leading_affect_tag(raw_completion)
        # 2. Drop invalid markers, keep valid ones so citations map 1:1.
        body_valid_markers = strip_dangling_markers(body, len(chunks))
        citations = citations_for_answer(chunks, body_valid_markers)
        # 3. Strip ALL markers for the spoken text (chunk_count=0 removes every
        #    [n]) so Cartesia never reads citation numbers aloud.
        spoken_text = strip_dangling_markers(body_valid_markers, 0).strip()
        no_answer = _is_no_answer(spoken_text)
        if no_answer:
            # The model reported the context lacks the answer: canonical copy,
            # no citations (nothing real to cite), keep any parsed affect.
            return NaomiVoiceAnswer(
                spoken_text=NAOMI_NO_ANSWER_TEXT,
                affect=affect,
                citations=(),
                no_answer=True,
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
            )
        return NaomiVoiceAnswer(
            spoken_text=spoken_text,
            affect=affect,
            citations=citations,
            no_answer=False,
            retrieval_ms=retrieval_ms,
            llm_ms=llm_ms,
        )


def _is_no_answer(spoken_text: str) -> bool:
    """True when the model's spoken answer is (essentially) the refusal line."""
    if not spoken_text:
        return True
    return NAOMI_NO_ANSWER_TEXT in spoken_text and len(spoken_text) <= len(NAOMI_NO_ANSWER_TEXT) + 8
