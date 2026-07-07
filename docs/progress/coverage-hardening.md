# Coverage Hardening — Progress Tracker

## North Star
Raise engine test coverage to the CI gate (line ≥90% / branch ≥85%) with GENUINE
adversarial tests (assert correct behavior, boundary-exact, no tautologies).
Exclude ONLY true hardware/network/DPAPI boundaries via coverage config + justified
`# pragma: no cover`. Never coverage-pad. Full suite stays green. Tooling stays
ad-hoc (not in pyproject/uv.lock).

## Baseline (authoritative, measured on main via `uv run --with pytest-cov`)
- Statement/line: 87.49%  (8442/9649 covered; 1207 missing)
- Branch: 76.31%  (1546/2026 covered; 480 missing)
- Combined percent_covered: 85.55%
- Suite: green (`-m 'not live_stt'`)

## Plan / checklist
- [x] Worktree feature/coverage-hardening off main
- [x] Install ad-hoc coverage tooling, measure baseline
- [x] Build gap map (missing lines/branches per file)
- [ ] T1 wiring/settings_value_validation + onboarding + app_settings gateway
- [ ] T2 agents tools (calendar/contacts/mappers/card builders)
- [ ] T3 index (sqlite_vec, embedder, watchdog, indexer, chunker, sql lookup)
- [ ] T4 naomi/voice (turn gateway/orchestrator/speaker, cartesia conn, dispatchers)
- [ ] T5 router provider clients + provider_key_live_validation
- [ ] T6 google (oauth flow, session, gateway, token store)
- [ ] T7 stt (weights downloader, keep_audio, live_capture, capture_model_loading, VAD, parakeet)
- [ ] T8 audio+detect (pyaudio backend, device listing, mic detector, desktop snapshot)
- [ ] T9 server + wiring dispatchers + security/secret_redaction + misc
- [ ] Add coverage config (.coveragerc) + justified pragmas for true boundaries
- [ ] Consolidated coverage re-run: line ≥90 / branch ≥85
- [ ] ruff + mypy clean on new tests; suite green
- [ ] evidence/coverage-report.md documenting final numbers + exclusions
- [ ] Commit + push feature/coverage-hardening

## Resume here
Dispatching T1-T9 test-writing agents (each owns disjoint NEW tests/ files).
Orchestrator owns all engine/ source pragma edits + coverage config.

## Decisions
- Tooling ad-hoc via `uv run --with pytest-cov --with coverage` — NOT added to pyproject/uv.lock.
- Most "boundary" files lazy-import hw/net libs -> testable via sys.modules fake injection.
  Only truly un-fakeable lines (real torch/nemo load, real socket, real DPAPI/ctypes) get pragma'd.
