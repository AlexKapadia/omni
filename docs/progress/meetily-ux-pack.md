# Progress: Meetily UX pack

**North Star:** Omni Settings/model UX matches Meetily’s remaining gaps (summary provider, Ollama pull, auto-summary, model lifecycle, polish).

**Resume here:** Both halves are implemented (engine T1/T2/T4/T6 above; UI
half below). Not committed per instructions — review the working tree diff
before committing.

## Checklist
- [x] T1 summary_provider + routing (engine done: settings validation/defaults, `prefer_summary_model(preferred_provider=...)`, plumbed through `fallback_executor`, `meeting_finalization_service`, `ask_query_command_dispatcher`/`ask_omni_answer_service`). **UI done**: `EngineSettings.summaryProvider`/`autoSummary` + parsing (`setup-settings-payloads.ts`), `toWireValues` mapping (`settings-actions.ts`), rewritten `summary-model-section.tsx`.
- [x] T2 ollama.list / ollama.pull (engine done: `ollama_command_payloads.py`, `ollama_command_dispatcher.py`, wired into `onboarding_settings_command_surface.py` + `server_default_service_factories.py`). **UI done**: `ollama-commands.ts` parsers, `setup-settings-repository.ts` wrappers (`listOllamaModels`/`pullOllamaModel`/`pingOllama` — verified to send NO `base_url`, since the payload schemas are `extra="forbid"` and the engine resolves its host from `OMNI_OLLAMA_BASE_URL`), `subscribeToOllamaPull` in `setup-settings-transport.ts`.
- [x] T3 auto_summary on capture.stopped — **UI done**: `wire-auto-summary.ts` (subscribes to `capture.stopped`, calls `finalizeMeeting` when `autoSummary` is on and no flow is pending), wired in `App.tsx`; `FinalizeMeetingPanel` hint.
- [x] T4 models.cancel / delete / open_folder (engine done: `models_lifecycle_payloads.py`, `models_lifecycle_ops.py`, dispatcher branches in `models_download_command_dispatcher.py`). **UI done**: repository wrappers + Cancel/Delete/Open-folder controls in `transcription-backend-section.tsx` / `whisper-model-list-section.tsx`, `reveal_path_in_explorer` Tauri command.
- [x] T5 toasts, auto-select, test connection, Parakeet polish (UI) — **done**: `toast-store.ts` + `toast-host.tsx` mounted in `App.tsx`; auto-select Whisper/Parakeet on `models.download.completed` (`models-download-completion.ts`); `ollama.ping`-backed "Test connection".
- [x] T6 tests green — engine-side: `test_router__prefer_summary_provider.py`, `test_ollama_http_client__ping_list.py`, `test_models_lifecycle__delete_and_cancel.py` all pass; full `pytest tests/` suite green (fixed pre-existing `FakeRouter`/`OnboardingSettingsCommandSurface` test-double drift from the earlier `preferred_model` plumbing). **UI-side**: `npx tsc --noEmit` shows zero *new* errors (141 pre-existing, unrelated, confirmed via before/after diff); `npx vitest run` is 74 files / 915 tests green, including 3 new suites (`toast-store`, `ollama-commands`, `wire-auto-summary`) and the 4 fixture files updated for the new `EngineSettings` fields.

## Decisions
- Builtin-AI = Ollama-backed recommended local models (not in-process GGUF).
- New modules preferred over growing settings-screen / validation files past 300.
- `prefer_summary_model`: `preferred_provider` (when mapped + keyed) prepends a slot using `preferred_model` if given, else the provider's own default model — it does not force an unrelated preferred_model onto a mismatched provider.
- **UI/engine contract fix (found during cross-check):** the initial UI draft passed `base_url` on `ollama.models.list`/`ollama.models.pull`/`ollama.ping`, and expected a `{ok, message, latencyMs}` ping reply. Neither matches the real engine (`extra="forbid"` payloads with no url field; the real ping reply is `{ok, version}` / `{ok:false, error}`). Fixed in `ollama-commands.ts` + `setup-settings-repository.ts` + `summary-model-section.tsx` before this pass finished — the Ollama endpoint field now takes effect purely through `settings.update({ollamaBaseUrl})`, which the engine mirrors into `OMNI_OLLAMA_BASE_URL`.
