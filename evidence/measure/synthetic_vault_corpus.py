"""Deterministic synthetic vault + labelled golden query set for retrieval eval.

Why synthetic: CLAUDE.md 3.12 forbids real PII / private conversations in any
test or measurement. This module fabricates a realistic-SHAPED personal
knowledge vault (fictional projects, meetings, people, decisions) with ZERO
real data, plus a golden set that labels, per query, which note(s) are the
correct answer. The queries paraphrase their target note rather than copying it,
so lexical retrieval is measured honestly — not gamed by exact-string overlap.

Everything is seeded and reproducible: the same corpus and labels regenerate on
every run, so the committed metrics are exactly reproducible.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoldenQuery:
    """One labelled retrieval task: a natural-language query and its answers.

    ``kind`` splits the golden set into two honest sub-populations:
      * "lexical"    — a natural question that shares key content words with the
                       target note (the common case).
      * "paraphrase" — a question worded with synonyms and minimal lexical
                       overlap, deliberately stressing the vocabulary-mismatch
                       weakness of any purely lexical index. Reporting these
                       separately is what keeps the BM25 result honest rather
                       than flattering.
    """

    query: str
    relevant_note_paths: frozenset[str]
    kind: str = "lexical"


# Each seed becomes one markdown note plus one or more paraphrase queries whose
# correct answer is that note. Content words are distinctive per note so a
# correct lexical match is possible but never a trivial full-phrase copy.
_SEEDS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "meetings/helios-kickoff.md",
        "Project Helios Kickoff",
        "The kickoff agreed the migration to a columnar warehouse would run in "
        "two phases. Priya owns the ingestion connectors; Marcus owns the "
        "backfill validation. Target cutover is the second sprint of the quarter.",
        ("who owns the backfill validation on the warehouse migration",
         "when is the Helios columnar cutover planned"),
    ),
    (
        "meetings/atlas-retro.md",
        "Atlas Retrospective",
        "The retro flagged flaky end-to-end tests as the top drag on velocity. "
        "The team decided to quarantine the flaky suite and gate merges on the "
        "stable subset until the payment webhook mocks are rewritten.",
        ("what did the Atlas team decide about flaky tests",
         "why were merges gated on a stable test subset"),
    ),
    (
        "projects/orion-pricing.md",
        "Orion Pricing Model",
        "Orion moves to seat-based pricing with a usage overage on API calls. "
        "The finance model assumes twelve percent monthly expansion and a nine "
        "month payback on the enterprise tier.",
        ("what pricing model did Orion adopt",
         "what is the assumed payback period on the enterprise tier"),
    ),
    (
        "people/dr-okonkwo.md",
        "Dr Okonkwo — Advisor",
        "Cardiology researcher advising on the signal-denoising approach for the "
        "wearable ECG. Prefers wavelet thresholding over a learned filter for "
        "auditability. Introduced by the Helios steering committee.",
        ("which advisor prefers wavelet thresholding for the ECG",
         "who advises on wearable ECG denoising"),
    ),
    (
        "decisions/db-choice.md",
        "Decision: Datastore for the Event Log",
        "We chose an append-only SQLite table with WAL over a hosted queue for "
        "the audit event log, because local durability and zero network egress "
        "matter more than throughput at our volume.",
        ("why did we pick SQLite for the audit event log",
         "what datastore backs the append-only audit log"),
    ),
    (
        "meetings/security-review.md",
        "Quarterly Security Review",
        "The review confirmed keys stay in DPAPI and never touch the UI process. "
        "Action item: add a kill-switch smoke test that proves all outbound model "
        "calls refuse when the flag is engaged.",
        ("where are the API keys stored according to the security review",
         "what kill-switch action item came out of the security review"),
    ),
    (
        "projects/nimbus-rollout.md",
        "Nimbus Rollout Plan",
        "Staged rollout behind a percentage flag: five percent, then twenty-five, "
        "then full. Rollback criterion is any regression in the p95 dictation "
        "latency beyond eight hundred milliseconds.",
        ("what is the Nimbus rollback criterion",
         "how is the Nimbus rollout staged"),
    ),
    (
        "notes/reading-embeddings.md",
        "Reading Notes: Dense Retrieval",
        "Bi-encoders trade recall for latency; reciprocal rank fusion combines a "
        "lexical BM25 list with a dense list without tuning weights. The fusion "
        "constant k of sixty is a robust default across the TREC collections.",
        ("what does reciprocal rank fusion combine",
         "what is a robust default for the RRF k constant"),
    ),
    (
        "meetings/vendor-cartesia.md",
        "Vendor Call: Voice Synthesis",
        "Evaluated a streaming text-to-speech vendor for the assistant voice. "
        "Latency to first audio was two hundred milliseconds; licensing forbids "
        "on-device caching of generated clips.",
        ("what was the time to first audio from the voice vendor",
         "what licensing restriction applies to the synthesized clips"),
    ),
    (
        "decisions/router-policy.md",
        "Decision: Tri-Provider Router Policy",
        "Groq handles instant extraction, Gemini Flash handles long-context bulk, "
        "and Claude handles agentic tool use. Each task type carries its own p95 "
        "latency budget which doubles as the per-attempt timeout.",
        ("which provider handles long-context bulk work",
         "what doubles as the per-attempt timeout in the router"),
    ),
    (
        "projects/vega-onboarding.md",
        "Vega Onboarding Wizard",
        "The wizard collects the vault path, validates the model manifest "
        "checksums, and stores provider keys encrypted before the first capture. "
        "It refuses to advance if a checksum mismatches.",
        ("what does the Vega wizard validate before first capture",
         "when does the onboarding wizard refuse to advance"),
    ),
    (
        "meetings/design-critique.md",
        "Design Critique: Approval Cards",
        "Approval cards must show the exact payload leaving the machine and a "
        "single approve action. No card auto-executes; Gmail actions are draft "
        "only and never send.",
        ("what must an approval card show before executing",
         "are Gmail actions allowed to send automatically"),
    ),
    (
        "notes/vad-gating.md",
        "Notes: Voice Activity Gating",
        "Silero VAD gates the transcriber with hysteresis: a higher enter "
        "threshold than exit threshold, plus a minimum speech and minimum silence "
        "duration to debounce brief pauses.",
        ("how does the VAD debounce brief pauses",
         "why is the enter threshold higher than the exit threshold"),
    ),
    (
        "decisions/audio-retention.md",
        "Decision: Audio Retention",
        "Raw audio is discarded immediately after transcription by default. A "
        "user toggle can retain clips, but retention is off unless explicitly "
        "enabled, and retained audio never leaves the device.",
        ("is raw audio kept after transcription by default",
         "where does retained audio go if the toggle is on"),
    ),
    (
        "projects/lyra-search.md",
        "Lyra Search Quality",
        "Chunking is heading-aware with sentence-aligned overlap so citations map "
        "to exact line ranges. A chunk never crosses a markdown heading boundary.",
        ("does a chunk ever cross a heading boundary",
         "why is chunking heading-aware in Lyra"),
    ),
    (
        "meetings/budget-planning.md",
        "Budget Planning Session",
        "The token spend cap for the evaluation sweep is fifty cents, metered "
        "against a counts-only endpoint. Overshoot must be reported honestly "
        "rather than hidden.",
        ("what is the token spend cap for the evaluation sweep",
         "how must overshoot on the token budget be handled"),
    ),
    (
        "people/marcus-liang.md",
        "Marcus Liang — Backend",
        "Owns the backfill validation and the migration runner. Advocates "
        "idempotent migrations keyed by content hash so re-runs are safe.",
        ("who advocates idempotent content-hash migrations",
         "what does Marcus Liang own on the backend"),
    ),
    (
        "notes/dictation-guard.md",
        "Notes: Dictation Faithfulness Guard",
        "The guard accepts a cleaned dictation only if every content word was "
        "already spoken, is a personal-dictionary term, or is a merge of adjacent "
        "spoken words. Any invented word is refused.",
        ("when does the dictation guard refuse a cleanup",
         "what merges does the faithfulness guard permit"),
    ),
    (
        "decisions/telemetry.md",
        "Decision: Zero Telemetry",
        "No usage analytics, no crash pings, no phone-home of any kind. The only "
        "network egress is explicit model calls the user triggers, logged in the "
        "audit trail.",
        ("what network egress does the app allow",
         "does the app send crash pings or usage analytics"),
    ),
    (
        "projects/phoenix-index.md",
        "Phoenix Index Layer",
        "Retrieval fuses a BM25 FTS5 ranking with an optional dense ranking. When "
        "the embedding model is absent the dense list is empty and fusion "
        "collapses to pure BM25 order, which is an honest documented degradation.",
        ("what happens to fusion when the embedding model is absent",
         "which lexical index backs the Phoenix retrieval"),
    ),
)

# Paraphrase queries: synonym-heavy, deliberately LOW lexical overlap with their
# target note. A purely lexical index (BM25) is expected to do measurably worse
# here than on the lexical queries above — that gap IS the honest finding, and it
# is exactly the vocabulary-mismatch weakness the dense bge-small tier closes.
_PARAPHRASE_QUERIES: tuple[tuple[str, str], ...] = (
    ("how quickly does the enterprise plan recover its cost", "projects/orion-pricing.md"),
    ("what is slowing the team's shipping speed the most", "meetings/atlas-retro.md"),
    ("under what condition do we abort the Nimbus release", "projects/nimbus-rollout.md"),
    ("does the app hold on to recordings once they are turned into text",
     "decisions/audio-retention.md"),
    ("does the software report anything back to its makers", "decisions/telemetry.md"),
    ("which service handles large document processing", "decisions/router-policy.md"),
    ("how does the system avoid toggling on and off during brief silences",
     "notes/vad-gating.md"),
    ("when will the tidy-up of my speech be rejected", "notes/dictation-guard.md"),
    ("what datastore keeps the permanent immutable record of every action taken",
     "decisions/db-choice.md"),
    ("how are the secret credentials protected on disk", "meetings/security-review.md"),
    ("can the assistant email people on its own without me confirming",
     "meetings/design-critique.md"),
    ("what does search fall back to with no vector model", "projects/phoenix-index.md"),
    ("why do the source references point to precise lines", "projects/lyra-search.md"),
    ("how much are we allowed to spend on the model evaluation run",
     "meetings/budget-planning.md"),
    ("what constant makes rank fusion robust without weight tuning",
     "notes/reading-embeddings.md"),
)

# Distractor notes add lexical noise (shared vocabulary, no query targets them)
# so BM25 must discriminate the right note from plausible neighbours — a harder,
# more realistic test than a corpus of unrelated documents.
_DISTRACTOR_TOPICS: tuple[str, ...] = (
    "warehouse capacity planning and connector throughput",
    "test suite maintenance and merge gating policy",
    "pricing experiments and expansion revenue modelling",
    "wearable sensor calibration and filter design",
    "event log durability and storage tradeoffs",
    "key management and process isolation controls",
    "staged feature flags and latency regression budgets",
    "retrieval fusion weighting and ranking experiments",
    "voice latency benchmarking and caching policy",
    "provider latency budgets and timeout handling",
)


def _distractor_body(rng: random.Random, topic: str) -> str:
    """A paragraph of plausible-but-irrelevant prose reusing corpus vocabulary."""
    fillers = (
        "The team reviewed", "An open question remains around", "Follow-up is needed on",
        "No decision was reached about", "Notes were captured on", "A spike explored",
    )
    tail = (
        "and the tradeoffs were documented for later.",
        "with owners to be assigned next sprint.",
        "pending a benchmark on realistic inputs.",
        "though the numbers still need validation.",
    )
    lines = [f"# {topic.title()}", ""]
    for _ in range(rng.randint(2, 4)):
        lines.append(f"{rng.choice(fillers)} {topic} {rng.choice(tail)}")
    return "\n".join(lines) + "\n"


def build_synthetic_vault(
    vault_root: Path, *, distractor_count: int = 30, seed: int = 20260707
) -> tuple[list[Path], list[GoldenQuery]]:
    """Write the synthetic vault to disk and return (written_paths, golden_set).

    distractor_count grows the corpus with noise notes so retrieval metrics are
    measured against a non-trivial number of competing documents. Deterministic
    for a fixed seed.
    """
    rng = random.Random(seed)
    written: list[Path] = []
    golden: list[GoldenQuery] = []

    for rel_path, title, body, queries in _SEEDS:
        note_path = vault_root / rel_path
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        written.append(note_path)
        for q in queries:
            golden.append(GoldenQuery(q, frozenset({rel_path}), kind="lexical"))

    for query_text, target_path in _PARAPHRASE_QUERIES:
        golden.append(GoldenQuery(query_text, frozenset({target_path}), kind="paraphrase"))

    for i in range(distractor_count):
        topic = _DISTRACTOR_TOPICS[i % len(_DISTRACTOR_TOPICS)]
        rel_path = f"archive/distractor-{i:03d}.md"
        note_path = vault_root / rel_path
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(_distractor_body(rng, topic), encoding="utf-8")
        written.append(note_path)

    return written, golden


def all_note_paths(written: Iterable[Path], vault_root: Path) -> list[str]:
    """Vault-relative POSIX paths, matching how the indexer stores note_path."""
    return [p.relative_to(vault_root).as_posix() for p in written]
