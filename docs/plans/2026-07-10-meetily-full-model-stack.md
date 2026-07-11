# Meetily-style Full Model Stack — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give Omni Meetily’s model setup: ggml Whisper catalog + downloadable cards, Parakeet cards, live engine selectable, Ollama-first summaries with persisted endpoint.

**Architecture:** Keep Omni’s Python engine as STT owner (no Tauri whisper-rs fork). Mirror Meetily’s catalog/URLs/UX; run Whisper via whisper.cpp Python binding on downloaded `ggml-*.bin` files; branch live capture on `stt_engine`.

**Tech stack:** Python engine + React Settings; HF `ggerganov/whisper.cpp` downloads; Ollama OpenAI-compat.

---

## Phase A — Whisper ggml catalog + download

### Task A1: Replace catalog with Meetily WHISPER_MODEL_CATALOG
- Files: `engine/stt/whisper_model_catalog.py`, `apps/ui/src/lib/whisper-model-catalog.ts`
- Download: `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{id}.bin`
- Presence: `ggml-{id}.bin` file under models dir
- Basic UI set: small, medium-q5_0, large-v3-q5_0, large-v3-turbo, large-v3
- Tests: catalog ids, URL builder, presence

### Task A2: Wire download through existing `models.download` whisper bundle
- Update allowlist in `models_download_payloads.py`
- Download single ggml file with progress (reuse HTTPS fetch pattern from model_weights_downloader)

### Task A3: Whisper backend loads ggml
- Prefer pywhispercpp / whisper.cpp binding on local `ggml-*.bin`
- Fail closed with install hint if binding missing
- Keep segment API for import; add `transcribe_window` → WordToken adapter for live

## Phase B — Live engine selection

### Task B1: `capture_model_loading.py` reads stt_engine + stt_model_id
- Parakeet path unchanged when engine=parakeet
- Whisper path: load ggml Whisper + Silero VAD
- Update runtime status honestly

### Task B2: UI copy — live uses selected provider

## Phase C — Meetily Settings UX

### Task C1: Transcription tab = provider dropdown + model cards
- Parakeet card(s) for core Parakeet download/select
- Whisper cards (basic + advanced accordion) Meetily-style
- Cloud STT remains tertiary

### Task C2: Summary = Ollama-first
- Add `ollama_base_url` setting (default `http://127.0.0.1:11434`)
- Default summary model `llama3.2`
- Provider registry reads setting then env
- UI: endpoint field + model select (Gemini/Claude/GPT/Ollama)

## Phase D — Verify
- Engine pytest for catalog/download/prefer
- Vitest for Settings transcription + summary
- Manual: download tiny ggml, select Whisper, start capture

## Out of scope (honest)
- Porting Meetily’s Rust whisper-rs into Tauri
- Meetily CDN Parakeet v3 multi-file ONNX layout (keep Omni’s existing Parakeet weight unless we add a second Parakeet id later)
- Cloud STT providers Meetily commented out (Deepgram etc.)
