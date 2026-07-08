"""Proactive vault suggestions — periodic RAG over recent transcript context.

Every ~30 s of meeting time, retrieves vault chunks related to what was just
said and emits ``vault.suggestion`` (same source shape as ``answers.hit``).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Protocol

import aiosqlite

from engine.ask.ask_answer_contracts import LiveAnswerHit, LiveAnswerSource
from engine.ask.citation_marker_mapping import truncate_quote
from engine.ask.structured_first_retrieval import retrieve_structured_first
from engine.index.hybrid_rrf_retriever import TIER_LIVE

DEFAULT_VAULT_POLL_SECONDS = 30.0
_MAX_WINDOW_LINES = 40
_QUERY_CHARS = 280
_TOP_N = 3

SuggestionEmitter = Callable[[str, tuple[LiveAnswerSource, ...], int], Awaitable[None]]


class ChunkRetrieverProtocol(Protocol):
    async def retrieve(self, *args, **kwargs): ...


class ProactiveVaultPoller:
    """Timer-driven vault retrieval from recent transcript text."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        retriever: ChunkRetrieverProtocol,
        emit: SuggestionEmitter,
        *,
        poll_seconds: float = DEFAULT_VAULT_POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._connection = connection
        self._retriever = retriever
        self._emit = emit
        self._poll_seconds = poll_seconds
        self._clock = clock
        self._today = today
        self._window: list[str] = []
        self._last_poll_at = clock()
        self._seen_topics: set[str] = set()

    async def on_final_segment(self, stream: str, text: str) -> None:
        if not text.strip():
            return
        prefix = "Me" if stream == "me" else "Them"
        self._window.append(f"{prefix}: {text.strip()}")
        if len(self._window) > _MAX_WINDOW_LINES:
            self._window = self._window[-_MAX_WINDOW_LINES:]

    async def tick(self, now: float | None = None) -> None:
        ts = now if now is not None else self._clock()
        if ts - self._last_poll_at < self._poll_seconds:
            return
        if not self._window:
            return
        self._last_poll_at = ts
        await self._poll()

    async def flush(self) -> None:
        if self._window:
            await self._poll()

    async def _poll(self) -> None:
        recent = "\n".join(self._window[-12:])
        query = recent[-_QUERY_CHARS:].strip()
        if len(query) < 20:
            return
        topic_key = query.lower()[:120]
        if topic_key in self._seen_topics:
            return
        started = self._clock()
        result = await retrieve_structured_first(
            self._connection,
            self._retriever,
            query,
            tier=TIER_LIVE,
            top_n=_TOP_N,
            enable_graph_expansion=False,
            today=self._today,
        )
        if not result.chunks:
            return
        self._seen_topics.add(topic_key)
        sources = tuple(
            LiveAnswerSource(
                note_path=chunk.note_path,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                heading_path=chunk.heading_path,
                snippet=truncate_quote(chunk.text),
                score=chunk.score,
            )
            for chunk in result.chunks
        )
        latency_ms = round((self._clock() - started) * 1000)
        await self._emit(query[:80], sources, latency_ms)
