"""Build the agents / dictation / Naomi and whole-system diagrams.

Strictly black-and-white, PNG + HTML each. Analysis-only (cairosvg).
"""

from __future__ import annotations

from diagram_svg_toolkit import Diagram


def build_agents() -> None:
    dia = Diagram(1400, 380, "Approval-Carded Actions")
    trans = dia.node(50, 150, 150, 62, "Transcript", "untrusted input")
    extract = dia.node(240, 150, 150, 62, "Extraction", "router: live_extraction")
    intent = dia.node(430, 150, 150, 62, "Intent", "structured decode")
    card = dia.node(620, 150, 168, 62, "Approval card", "shows exact payload",
                    emphasis=True)
    approve = dia.node(828, 150, 150, 62, "User approves", "explicit action")
    execute = dia.node(1018, 150, 150, 62, "Executor", "least privilege")
    for a, b in ((trans, extract), (extract, intent), (intent, card), (card, approve),
                 (approve, execute)):
        dia.edge(a.port("right"), b.port("left"))
    cal = dia.node(1210, 60, 150, 52, "Calendar event", "")
    contact = dia.node(1210, 132, 150, 52, "Contact upsert", "")
    gmail = dia.node(1210, 204, 150, 52, "Gmail DRAFT", "never send", emphasis=True)
    for t in (cal, contact, gmail):
        dia.edge(execute.port("right"), t.port("left"), elbow=True)
    audit = dia.node(1018, 268, 150, 56, "Audit log", "append-only")
    dia.edge(execute.port("bottom"), audit.port("top"))
    dia.boundary(610, 128, 386, 168, "approval before execute")
    dia.caption(
        "No tool runs without an approved card; Gmail is draft-only, never send. Every "
        "executed action is written to an immutable audit log (what, when, which provider)."
    )
    dia.save("diagram_approval_agents")


def build_dictation() -> None:
    dia = Diagram(1360, 360, "Push-to-Talk Dictation")
    ptt = dia.node(50, 140, 150, 62, "Global hotkey", "push-to-talk")
    cap = dia.node(240, 140, 150, 62, "Capture + STT", "mic only")
    clean = dia.node(430, 140, 158, 62, "Router cleanup", "dictation_cleanup")
    guard = dia.node(632, 140, 168, 62, "Faithfulness guard", "deterministic",
                     emphasis=True)
    for a, b in ((ptt, cap), (cap, clean), (clean, guard)):
        dia.edge(a.port("right"), b.port("left"))
    cleaned = dia.node(860, 66, 168, 58, "Cleaned text", "every word spoken")
    raw = dia.node(860, 214, 168, 58, "Raw fallback", "guard refused")
    dia.edge(guard.port("right"), cleaned.port("left"), "faithful", elbow=True)
    dia.edge(guard.port("right"), raw.port("left"), "hallucination", elbow=True, dashed=True)
    inject = dia.node(1090, 140, 150, 62, "Insert at cursor", "0 false-negatives")
    dia.edge(cleaned.port("right"), inject.port("left"), elbow=True)
    dia.edge(raw.port("right"), inject.port("left"), elbow=True)
    dia.caption(
        "The guard accepts a cleanup only if every content word was actually spoken; any "
        "hallucination falls back to the raw text (measured 0 false-negatives over 1020 cases)."
    )
    dia.save("diagram_dictation")


def build_naomi() -> None:
    dia = Diagram(1240, 320, "Live Answer Loop (Naomi)")
    q = dia.node(50, 130, 158, 62, "Question spotter", "cadence + dedupe")
    retr = dia.node(258, 130, 158, 62, "Retrieve (RAG)", "hybrid, top-8")
    synth = dia.node(466, 130, 158, 62, "Synthesize", "router: ask_synthesis")
    cite = dia.node(674, 130, 158, 62, "Citation guard", "no dangling markers",
                    emphasis=True)
    card = dia.node(882, 130, 168, 62, "Live answer card", "quotes + provenance")
    for a, b in ((q, retr), (retr, synth), (synth, cite), (cite, card)):
        dia.edge(a.port("right"), b.port("left"))
    empty = dia.node(466, 226, 158, 54, "\"not in your notes\"", "honest refusal")
    dia.edge(retr.port("bottom"), empty.port("top"), "no chunks", dashed=True)
    dia.caption(
        "Answers come only from the user's own notes and transcripts; weak retrieval refuses "
        "honestly (zero provider calls). Citation exactness measured 1.0 over 55 answers."
    )
    dia.save("diagram_naomi_live_answer")


def build_system() -> None:
    dia = Diagram(1300, 760, "Omni — System Architecture")
    ui = dia.node(360, 66, 400, 66, "Tauri 2 shell + React UI", "windows, tray, global hotkeys")

    # Engine sidecar container with a header strip and six subsystem nodes.
    dia.node(80, 210, 880, 350, "", "")
    dia.node(104, 246, 832, 34, "Python engine sidecar (PyInstaller)  -  FastAPI + WebSocket", "")
    sub = [
        ("Capture + STT", "VAD -> Parakeet"), ("Index / RAG", "chunk -> BM25/dense"),
        ("AI Router", "Groq/Gemini/Claude"), ("Agents + Executor", "approval-carded"),
        ("Notes enhance", "managed markers"), ("Dictation", "faithfulness guard"),
    ]
    for i, (label, s) in enumerate(sub):
        col, rrow = i % 3, i // 3
        dia.node(104 + col * 284, 306 + rrow * 112, 258, 82, label, s)
    dia.edge(ui.port("bottom"), (520, 210), "WebSocket protocol v1")

    # Providers sit outside the kill-switchable egress boundary (no overlap).
    dia.node(1010, 250, 210, 280, "", "")
    dia.node(1034, 268, 162, 28, "Model providers", "")
    for i, name in enumerate(("Groq", "Gemini Flash", "Claude Sonnet")):
        dia.node(1034, 316 + i * 66, 162, 52, name, "")
    dia.boundary(1000, 236, 230, 306, "egress (kill-switch)")
    dia.edge((962, 347), (1010, 347), "AI Router only")

    # Local, engine-only data plane along the bottom.
    keys = dia.node(120, 620, 250, 74, "DPAPI key store", "engine-only, never in UI",
                    emphasis=True)
    store = dia.node(430, 620, 300, 74, "Local storage", "SQLite + Obsidian vault")
    dia.node(790, 620, 320, 74, "Zero telemetry", "no phone-home, ever", emphasis=True)
    dia.edge((250, 560), keys.port("top"))
    dia.edge((560, 560), store.port("top"))
    dia.caption(
        "Deterministic local core (capture, storage, approval, audit) with learned layers on "
        "top (STT, retrieval, synthesis). Keys live only in the engine via DPAPI; the only "
        "egress is explicit, kill-switchable model calls. Audio discarded post-transcription."
    )
    dia.save("diagram_system_architecture")


def main() -> None:
    build_agents()
    build_dictation()
    build_naomi()
    build_system()
    print("built agents + dictation + naomi + system diagrams")


if __name__ == "__main__":
    main()
