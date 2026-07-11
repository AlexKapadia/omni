# Meetily UX Pack — Implementation Plan

> **For Claude:** Execute task-by-task. Prefer new small modules over growing files already >300 lines.

**Goal:** Ship the remaining Meetily-inspired product gaps: summary provider config, Ollama list/pull, auto-summary, model lifecycle (cancel/delete/open), toasts/auto-select, test connection, Parakeet cards, and a local summary path.

**Builtin-AI decision:** Local summaries via Ollama pull of recommended models (`gemma3:1b`, `llama3.2`) with Meetily-style cards — not a second GGUF runtime. True in-process GGUF is deferred (Ollama already covers privacy-local).

---

## Task 1 — `summary_provider` setting
- Keys: `summary_provider` (`ollama|gemini|anthropic|openai|builtin-ai`)
- Default `ollama`; keep `summary_model_id` + `ollama_base_url`
- `prefer_summary_model` respects provider (force that provider’s slot first)
- UI: rewrite `summary-model-section.tsx`, wire into AiTab (don’t grow settings-screen much)

## Task 2 — Ollama list + pull
- Commands: `ollama.models.list`, `ollama.models.pull` (+ progress/completed events)
- UI: model combobox + Pull button in summary section

## Task 3 — Auto-summary
- Setting `auto_summary` bool (default false)
- On `capture.stopped`, if enabled → `finalizeMeeting`
- Toggle in Settings + Live finalize panel hint

## Task 4 — Model lifecycle
- `models.cancel`, `models.delete` `{file}`, `models.open_folder` → path reply; UI opens via Tauri
- Wire into transcription / models sections

## Task 5 — Polish
- Lightweight toast store + host
- Auto-select Whisper/Parakeet after download complete
- `ollama.ping` / reuse keys.validate for “Test connection”
- Parakeet card polish (already partially done)

## Task 6 — Verify
- pytest for new protocol/dispatch
- vitest for summary section + models actions
