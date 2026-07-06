"""Typed seams the ask services depend on (retriever + router).

Purpose: narrow structural protocols so both ask services are unit-tested
against deterministic fakes while the real ``HybridRrfRetriever`` and
``ProviderRouter`` satisfy them unchanged — no test ever needs a network
or a vector model (no-network-in-unit-tests rule).
Pipeline position: imported by ``ask_omni_answer_service``,
``live_answers_spotter``, and ``structured_first_retrieval``.
"""

from typing import Protocol

from engine.index.hybrid_rrf_retriever import DEFAULT_TOP_N, TIER_LIVE
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.router.completion_contract import (
    ChatMessage,
    RoutedCompletion,
    ToolSpec,
)


class ChunkRetrieverProtocol(Protocol):
    """What the ask layer needs from a retriever (HybridRrfRetriever fits)."""

    async def retrieve(
        self,
        query: str,
        tier: str = TIER_LIVE,
        top_n: int = DEFAULT_TOP_N,
        enable_graph_expansion: bool = True,
    ) -> list[RetrievedChunk]:
        """Tiered hybrid retrieval; every result carries exact citation."""
        ...


class CompletionRouterProtocol(Protocol):
    """What the ask layer needs from the router (ProviderRouter fits)."""

    async def route(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        """Execute one task through the provider chain (kill-switch gated)."""
        ...
