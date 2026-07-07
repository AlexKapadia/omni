"""Regenerate every committed evidence/data/*.json from the real system.

Runs the hermetic (no-network) measurement harnesses in sequence so all figures
and diagrams can be rebuilt deterministically from freshly-measured data. The
live bounded router sample is intentionally EXCLUDED here — it makes real,
metered provider calls and is run explicitly via
measure_router_live_bounded_sample.py so a plain regen never spends money.

Usage (from the repo root, with the engine venv on PYTHONPATH):
    python evidence/measure/run_all_measurements.py
"""

from __future__ import annotations

import measure_ask_latency_and_citation_exactness as ask
import measure_determinism_proofs as determinism
import measure_dictation_faithfulness_guard as dictation
import measure_retrieval_latency_scaling as scaling
import measure_retrieval_quality_bm25 as retrieval
import measure_router_cost_and_fallback as router_cost
import measure_stt_chunk_merge_latency_and_fidelity as stt
import measure_test_suite_inventory as inventory

_HARNESSES = (
    ("STT chunk-merge latency + fidelity", stt.main),
    ("Retrieval quality (BM25)", retrieval.main),
    ("Retrieval latency scaling", scaling.main),
    ("Router cost + fallback", router_cost.main),
    ("Ask citation exactness + latency", ask.main),
    ("Dictation faithfulness guard", dictation.main),
    ("Determinism proofs", determinism.main),
    ("Test-suite inventory + coverage", inventory.main),
)


def main() -> None:
    for name, run in _HARNESSES:
        print(f"\n=== {name} ===")
        run()
    print("\nAll hermetic measurements regenerated. Run the live sample separately.")


if __name__ == "__main__":
    main()
