# Progress: Meetily full model stack

**North Star:** Omni Settings model setup matches Meetily — ggml Whisper cards, Parakeet cards, live selectable engine, Ollama-first summaries.

**Resume here:** COMPLETE — verify in running app (download tiny ggml, select Whisper, start capture; set Ollama endpoint).

## Checklist
- [x] A1 ggml catalog (engine + UI) — Meetily WHISPER_MODEL_CATALOG
- [x] A2 download ggml via models.download (HF ggerganov/whisper.cpp)
- [x] A3 Whisper backend loads ggml via pywhispercpp + live WordToken adapter
- [x] B1 capture_model_loading branches on stt_engine
- [x] C1 Meetily-style transcription Settings UI (provider + cards)
- [x] C2 ollama_base_url + Ollama-first summary UI
- [x] D tests green (870 vitest; catalog/protocol/prefer pytest)

## Decisions
- Python engine owns STT (not Tauri whisper-rs).
- Whisper files = Meetily `ggml-*.bin` from `ggerganov/whisper.cpp`.
- Runtime = `pywhispercpp` (`uv sync --extra whisper`).
- Parakeet keeps Omni’s existing single-file weight; UI is Meetily-style card.
- Default summary model = `llama3.2`; default Ollama URL = `http://127.0.0.1:11434`.
