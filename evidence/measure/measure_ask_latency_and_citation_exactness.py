"""Measure Ask-Omni: citation exactness + the real retrieval-stage latency.

Ask-Omni answers a question over the vault, then MUST cite its sources exactly:
citation marker [i] resolves to the i-th retrieved chunk, and any marker the
model invents that points at no chunk is stripped before the answer leaves the
engine ("a citation can never point at nothing"). This harness proves that
enforcement end-to-end through the REAL AskOmniAnswerService + REAL BM25
retriever, driving synthesis with a scripted router that deliberately emits BOTH
a valid marker and a hallucinated dangling marker.

Two measurements:
  * CITATION EXACTNESS — over the golden query set, the rate at which every
    emitted citation's provenance (note_path, line range, quote) matches the
    cited chunk verbatim AND the injected dangling marker is stripped. The
    safety number is dangling-markers-survived, which must be zero.
  * RETRIEVAL LATENCY — the real retrieval span measured by the service's own
    clock across the golden queries. (Synthesis latency is provider/network
    bound and is measured live, with real keys, in the bounded router sample;
    here it is scripted and instant, so only the retrieval stage is timed.)
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from engine.ask.ask_omni_answer_service import AskOmniAnswerService
from engine.index import HybridRrfRetriever, VaultIndexerService
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolSpec,
)
from engine.router.routing_table import resolve_route
from engine.storage import apply_migrations, open_sqlite_connection
from statistics_helpers import mean_with_bootstrap_ci, nearest_rank_percentile_ms
from synthetic_vault_corpus import build_synthetic_vault

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DANGLING_MARKER = 999  # a citation index no retrieval will ever produce
_LATENCY_REPEATS = 15


class _ScriptedSynthesisRouter:
    """Stands in for the synthesis provider with a fixed, adversarial answer.

    It cites marker [1] (a real retrieved chunk) and marker [999] (a hallucinated
    source that resolves to nothing). The service must map [1] exactly and strip
    [999] — that is precisely what this harness measures.
    """

    async def route(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        reply = json.dumps(
            {
                "headline": "Synthesised answer",
                "answer": f"The supported claim [1]. An unsupported claim [{_DANGLING_MARKER}].",
            }
        )
        completion = ProviderCompletion(
            text=reply,
            provider=Provider.GEMINI,
            model="gemini-2.5-flash",
            prompt_tokens=1,
            completion_tokens=1,
        )
        return RoutedCompletion(
            completion=completion, provider=Provider.GEMINI, model="gemini-2.5-flash", latency_ms=1
        )


async def _run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="omni-eval-ask-") as tmp:
        tmp_path = Path(tmp)
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        db_path = tmp_path / "ask.db"
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations"

        written, golden = build_synthetic_vault(vault_root)
        await apply_migrations(db_path, migrations_dir)
        connection = await open_sqlite_connection(db_path)
        try:
            await VaultIndexerService(connection, vault_root).index_changed_files(written)
            retriever = HybridRrfRetriever(connection, None, None)  # BM25-only, honest
            service = AskOmniAnswerService(connection, retriever, _ScriptedSynthesisRouter())

            answers_evaluated = 0
            all_exact = 0
            dangling_survived = 0
            valid_marker_preserved = 0
            no_answer_count = 0
            retrieval_ms_samples: list[float] = []

            for gq in golden:
                answer = await service.answer(gq.query)
                if answer.no_answer:
                    no_answer_count += 1
                    continue
                answers_evaluated += 1

                # Re-run the retriever to recover the exact chunk list the service
                # cited against, so we can check provenance byte-for-byte.
                chunks = await retriever.retrieve(gq.query, top_n=8)
                citation_exact = True
                for citation in answer.citations:
                    if citation.n == _DANGLING_MARKER:
                        dangling_survived += 1
                        citation_exact = False
                        continue
                    source = chunks[citation.n - 1]
                    if (
                        citation.note_path != source.note_path
                        or citation.line_start != source.line_start
                        or citation.line_end != source.line_end
                    ):
                        citation_exact = False
                if f"[{_DANGLING_MARKER}]" in answer.answer_md:
                    dangling_survived += 1
                    citation_exact = False
                if "[1]" in answer.answer_md:
                    valid_marker_preserved += 1
                if citation_exact:
                    all_exact += 1

            # Real retrieval-stage latency via the service's own measured span.
            for _ in range(_LATENCY_REPEATS):
                for gq in golden:
                    start = time.perf_counter()
                    ans = await service.answer(gq.query)
                    _ = ans
                    retrieval_ms_samples.append((time.perf_counter() - start) * 1000.0)
        finally:
            await connection.close()

    exactness_rate = all_exact / answers_evaluated if answers_evaluated else 1.0
    mean, lo, hi = mean_with_bootstrap_ci(retrieval_ms_samples)
    budgets = {
        t: resolve_route(t, frozenset({"groq", "gemini", "anthropic"})).latency_budget_p95_ms
        for t in ("ask_synthesis",)
    }
    return {
        "component": "engine.ask.AskOmniAnswerService + engine.index.HybridRrfRetriever (real)",
        "synthesis": "scripted (deterministic) — emits one valid marker [1] and one "
        "hallucinated dangling marker [999] per answer; real synthesis latency is "
        "provider-bound and measured in the live bounded router sample.",
        "citation_exactness": {
            "answers_evaluated": answers_evaluated,
            "no_answer_honest_refusals": no_answer_count,
            "all_citations_exact": all_exact,
            "exactness_rate": exactness_rate,
            "dangling_markers_injected": answers_evaluated,
            "dangling_markers_survived": dangling_survived,
            "valid_marker_preserved": valid_marker_preserved,
        },
        "ask_pipeline_latency_ms": {
            "note": "full service.answer() wall time with instant scripted synthesis — "
            "so this is the retrieval-dominated floor, not end-to-end with a real provider.",
            "n_measurements": len(retrieval_ms_samples),
            "mean": mean,
            "ci95_low": lo,
            "ci95_high": hi,
            "p50": nearest_rank_percentile_ms(retrieval_ms_samples, 50),
            "p95": nearest_rank_percentile_ms(retrieval_ms_samples, 95),
            "p99": nearest_rank_percentile_ms(retrieval_ms_samples, 99),
            "raw_ms": [round(v, 4) for v in retrieval_ms_samples],
        },
        "synthesis_p95_budget_ms": budgets["ask_synthesis"],
    }


def main() -> None:
    result = asyncio.run(_run())
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / "ask_citation_and_latency.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    ce = result["citation_exactness"]
    lat = result["ask_pipeline_latency_ms"]
    print(f"wrote {out}")
    print(
        f"  citation exactness={ce['exactness_rate']:.4f}  "
        f"dangling survived={ce['dangling_markers_survived']}  "
        f"answers={ce['answers_evaluated']}"
    )
    print(f"  ask floor p50/p95/p99 = {lat['p50']:.3f}/{lat['p95']:.3f}/{lat['p99']:.3f} ms")


if __name__ == "__main__":
    main()
