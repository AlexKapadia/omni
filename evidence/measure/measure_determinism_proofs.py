"""Prove the deterministic paths are byte-for-byte reproducible over N runs.

CLAUDE.md mandates that any reproducible path yields identical outputs for
identical inputs across repeated runs. This harness runs each deterministic core
component many times on fixed inputs and confirms the set of distinct outputs has
size exactly one. A single divergence would be a determinism failure.

Covered (all real engine code, headless): the STT chunk merger, the VAD gating
state machine, the router cost function (Decimal), the dictation faithfulness
guard, and the BM25 retriever ranking.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from engine.dictation.dictation_cleanup import cleanup_output_is_faithful
from engine.index import HybridRrfRetriever, VaultIndexerService
from engine.router.model_pricing import estimate_cost_usd
from engine.storage import apply_migrations, open_sqlite_connection
from engine.stt.streaming_chunk_merger import StreamingChunkMerger
from engine.stt.vad_gating_state_machine import VadGatingStateMachine
from engine.stt.word_token_types import TranscribedWindow, WordToken
from synthetic_vault_corpus import build_synthetic_vault

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_RUNS = 200


def _chunk_merge_signature() -> str:
    windows = [
        TranscribedWindow(
            0, 0.0, 4.0, (WordToken("alpha", 0.1, 0.5), WordToken("beta", 0.6, 1.0))
        ),
        TranscribedWindow(
            1, 3.2, 7.2, (WordToken("beta", 3.3, 3.7), WordToken("gamma", 4.0, 4.4))
        ),
    ]
    merger = StreamingChunkMerger(overlap_s=0.8)
    for window in windows:
        merger.add_window(window)
    return "|".join(f"{w.text}:{w.t_start:.3f}" for w in merger.flush())


def _vad_gating_signature() -> str:
    script = [0.1, 0.2, 0.7, 0.8, 0.9, 0.6, 0.2, 0.1, 0.05, 0.7, 0.8, 0.1]
    machine = VadGatingStateMachine()
    events: list[str] = []
    for i, prob in enumerate(script):
        for event, at in machine.process(prob, i * 0.032, (i + 1) * 0.032):
            events.append(f"{event}:{at:.3f}")
    for event, at in machine.force_close(len(script) * 0.032):
        events.append(f"{event}:{at:.3f}")
    return "|".join(events)


def _cost_signature() -> str:
    parts = [
        str(estimate_cost_usd(model, p, c))
        for model in ("llama-3.3-70b-versatile", "gemini-2.5-flash", "claude-sonnet-4-5")
        for p, c in ((1000, 500), (128_000, 4096))
    ]
    return "|".join(parts)


def _guard_signature() -> str:
    cases = [
        ("send the report today", "Send the report today."),
        ("meet at three no wait four", "meet at four"),
        ("the report", "the quarterly report"),
        ("we should ship", "we should not ship"),
    ]
    return "|".join(str(cleanup_output_is_faithful(r, c)) for r, c in cases)


async def _retrieval_signature() -> str:
    with tempfile.TemporaryDirectory(prefix="omni-eval-determinism-") as tmp:
        tmp_path = Path(tmp)
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        db_path = tmp_path / "det.db"
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
        written, golden = build_synthetic_vault(vault_root, distractor_count=10)
        await apply_migrations(db_path, migrations_dir)
        connection = await open_sqlite_connection(db_path)
        try:
            await VaultIndexerService(connection, vault_root).index_changed_files(written)
            retriever = HybridRrfRetriever(connection, None, None)
            signatures: list[str] = []
            for _ in range(20):  # repeat retrieval within one indexed DB
                per_query: list[str] = []
                for gq in golden[:10]:
                    chunks = await retriever.retrieve(
                        gq.query, top_n=8, enable_graph_expansion=False
                    )
                    per_query.append(",".join(c.note_path for c in chunks))
                signatures.append(";".join(per_query))
        finally:
            await connection.close()
    return "UNIQUE" if len(set(signatures)) == 1 else "DIVERGED"


def _run() -> dict[str, Any]:
    checks = {
        "stt_chunk_merge": _chunk_merge_signature,
        "vad_gating_state_machine": _vad_gating_signature,
        "router_cost_decimal": _cost_signature,
        "dictation_faithfulness_guard": _guard_signature,
    }
    results: dict[str, Any] = {}
    all_deterministic = True
    for name, fn in checks.items():
        outputs = {fn() for _ in range(_RUNS)}
        deterministic = len(outputs) == 1
        all_deterministic = all_deterministic and deterministic
        results[name] = {
            "runs": _RUNS,
            "distinct_outputs": len(outputs),
            "deterministic": deterministic,
        }

    retrieval_verdict = asyncio.run(_retrieval_signature())
    retrieval_ok = retrieval_verdict == "UNIQUE"
    all_deterministic = all_deterministic and retrieval_ok
    results["bm25_retrieval_ranking"] = {
        "repeats": 20,
        "distinct_outputs": 1 if retrieval_ok else 2,
        "deterministic": retrieval_ok,
    }

    return {
        "method": "Each deterministic path is run on fixed inputs many times; the "
        "number of distinct outputs must be exactly 1.",
        "runs_per_check": _RUNS,
        "checks": results,
        "all_paths_deterministic": all_deterministic,
    }


def main() -> None:
    result = _run()
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / "determinism.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(f"  all_paths_deterministic = {result['all_paths_deterministic']}")
    for name, info in result["checks"].items():
        print(f"    {name}: distinct_outputs={info['distinct_outputs']}")


if __name__ == "__main__":
    main()
