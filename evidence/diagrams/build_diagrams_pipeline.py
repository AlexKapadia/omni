"""Build the pipeline component diagrams (capture->STT, index, router, enhance).

Strictly black-and-white, PNG + HTML each. Analysis-only (cairosvg).
"""

from __future__ import annotations

from itertools import pairwise

from diagram_svg_toolkit import Diagram, Node


def _hflow(dia: Diagram, y: float, labels: list[tuple[str, str]], *, x0: float = 60,
           w: float = 158, h: float = 64, gap: float = 46) -> list[Node]:
    """Place a left-to-right row of nodes and connect them right->left."""
    nodes: list[Node] = []
    x = x0
    for label, sub in labels:
        nodes.append(dia.node(x, y, w, h, label, sub))
        x += w + gap
    for a, b in pairwise(nodes):
        dia.edge(a.port("right"), b.port("left"))
    return nodes


def build_capture_stt() -> None:
    dia = Diagram(1540, 340, "Capture -> Transcription")
    mic = dia.node(60, 90, 158, 64, "Microphone", "the user's voice")
    loop = dia.node(60, 196, 158, 64, "WASAPI loopback", "other participants")
    resample = dia.node(264, 143, 150, 64, "Resample 16 kHz", "soxr")
    dia.edge(mic.port("right"), resample.port("left"), elbow=True)
    dia.edge(loop.port("right"), resample.port("left"), elbow=True)
    rest = _hflow(
        dia, 143,
        [("Silero VAD gate", "hysteresis"), ("Window assembler", "overlap 0.8 s"),
         ("Parakeet-TDT", "streaming STT"), ("Chunk merger", "dedup overlap"),
         ("Transcript", "two labelled streams")],
        x0=460,
    )
    dia.edge(resample.port("right"), rest[0].port("left"))
    dia.boundary(40, 68, 380, 218, "two labelled streams, headphone-proof")
    dia.caption(
        "Silero VAD gates Parakeet-TDT; overlapping windows are merged verbatim. "
        "Audio is discarded after transcription by default (local-only invariant)."
    )
    dia.save("diagram_capture_stt_pipeline")


def build_index_retrieval() -> None:
    dia = Diagram(1180, 420, "Index & Retrieval")
    watch = dia.node(60, 80, 160, 62, "Vault watcher", "sha256 change detect")
    chunk = dia.node(60, 176, 160, 62, "Markdown chunker", "heading-aware")
    dia.edge(watch.port("bottom"), chunk.port("top"))
    bm25 = dia.node(300, 96, 170, 62, "BM25 / FTS5", "lexical (always on)")
    dense = dia.node(300, 192, 170, 62, "bge-small + sqlite-vec", "dense (weights absent)",
                     dashed=True)
    dia.edge(chunk.port("right"), bm25.port("left"), elbow=True)
    dia.edge(chunk.port("right"), dense.port("left"), elbow=True)
    rrf = dia.node(548, 144, 150, 62, "RRF fusion", "k = 60")
    dia.edge(bm25.port("right"), rrf.port("left"), elbow=True)
    dia.edge(dense.port("right"), rrf.port("left"), "empty -> BM25 only", elbow=True, dashed=True)
    graph = dia.node(760, 144, 158, 62, "Graph expansion", "wikilinks + entities")
    top = dia.node(978, 144, 150, 62, "Top-8 chunks", "with citations")
    dia.edge(rrf.port("right"), graph.port("left"))
    dia.edge(graph.port("right"), top.port("left"))
    dia.caption(
        "Hybrid by design: BM25 fused with a dense list via reciprocal rank fusion. "
        "With bge-small weights absent the dense list is empty and fusion collapses to "
        "BM25 (measured Recall@5 1.0 lexical / 0.67 paraphrase)."
    )
    dia.save("diagram_index_retrieval")


def build_router() -> None:
    dia = Diagram(1180, 460, "Tri-Provider AI Router")
    task = dia.node(60, 200, 150, 64, "Task", "typed request")
    kill = dia.node(250, 200, 150, 64, "Kill-switch gate", "fail closed", emphasis=True)
    resolve = dia.node(440, 200, 158, 64, "Resolve route", "deny by default")
    dia.edge(task.port("right"), kill.port("left"))
    dia.edge(kill.port("right"), resolve.port("left"))
    groq = dia.node(690, 100, 168, 60, "Groq llama-3.3", "instant extraction")
    gem = dia.node(690, 202, 168, 60, "Gemini Flash", "long-context bulk")
    claude = dia.node(690, 304, 168, 60, "Claude Sonnet", "agentic tools")
    for prov, lbl in ((groq, "primary"), (gem, "fallback"), (claude, "if keyed")):
        dia.edge(resolve.port("right"), prov.port("left"), lbl, elbow=True)
    ledger = dia.node(920, 202, 168, 60, "Append-only ledger", "cost + latency")
    for prov in (groq, gem, claude):
        dia.edge(prov.port("right"), ledger.port("left"), elbow=True)
    dia.boundary(672, 78, 200, 308, "network egress boundary")
    dia.caption(
        "Each task type carries a p95 latency budget that doubles as the per-attempt timeout; "
        "retry-once then cascade. Cost is Decimal-exact (0 mismatches over 24 grid points)."
    )
    dia.save("diagram_router")


def build_enhance() -> None:
    dia = Diagram(1180, 320, "Notes Enhancement")
    notes = dia.node(60, 70, 168, 64, "Rough notes", "user-authored")
    trans = dia.node(60, 176, 168, 64, "Transcript", "labelled streams")
    fuse = dia.node(300, 123, 168, 64, "Fuse (router)", "enhanced_notes task")
    dia.edge(notes.port("right"), fuse.port("left"), elbow=True)
    dia.edge(trans.port("right"), fuse.port("left"), elbow=True)
    managed = dia.node(520, 123, 190, 64, "Managed region", "<!-- omni:managed -->",
                       emphasis=True)
    writer = dia.node(760, 123, 168, 64, "Vault writer", "append / new file only")
    vault = dia.node(978, 123, 150, 64, "Obsidian vault", "user text untouched")
    dia.edge(fuse.port("right"), managed.port("left"))
    dia.edge(managed.port("right"), writer.port("left"))
    dia.edge(writer.port("right"), vault.port("left"))
    dia.caption(
        "Enhanced notes land strictly between managed markers; user-authored text is never "
        "edited. The information boundary is enforced in the writer, not by convention."
    )
    dia.save("diagram_enhance_pipeline")


def main() -> None:
    build_capture_stt()
    build_index_retrieval()
    build_router()
    build_enhance()
    print("built pipeline diagrams")


if __name__ == "__main__":
    main()
