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
- [x] T1 wiring/settings_value_validation + onboarding + app_settings gateway (55 tests, 0 excl)
- [x] T2 agents tools (60 tests; flagged approval_card_builder L148-150,174-176 unreachable ValidationError)
- [ ] T3 index (sqlite_vec, embedder, watchdog, indexer, chunker, sql lookup)
- [ ] T4 naomi/voice (turn gateway/orchestrator/speaker, cartesia conn, dispatchers)
- [x] T5 router provider clients + provider_key_live_validation (30 tests, 0 new excl)
- [x] T6 google (oauth flow, session, gateway, token store) (32 tests, 0 excl — real loopback)
- [ ] T7 stt (weights downloader, keep_audio, live_capture, capture_model_loading, VAD, parakeet)
- [ ] T8 audio+detect (pyaudio backend, device listing, mic detector, desktop snapshot)
- [ ] T9 server + wiring dispatchers + security/secret_redaction + misc
- [ ] Add coverage config (.coveragerc) + justified pragmas for true boundaries
- [ ] Consolidated coverage re-run: line ≥90 / branch ≥85
- [ ] ruff + mypy clean on new tests; suite green
- [ ] evidence/coverage-report.md documenting final numbers + exclusions
- [ ] Commit + push feature/coverage-hardening

## Resume here
PRELIMINARY consolidated coverage (T1-T3,T5-T8,T10 committed; T4/T9 files present, not yet in run):
  LINE 96.59% / BRANCH 91.61% — GATE ALREADY MET (>=90 / >=85), no candidate pragmas needed yet.
Next: await T4+T9 completion notifications, verify their files green, run AUTHORITATIVE final --cov
(whole suite), confirm gate, finalize evidence report, ruff+mypy on new tests, commit+push.
If resuming cold: all test files are under tests/ (committed batch 2c766db + T4/T9 files); run
`uv run --with pytest-cov --with coverage pytest --cov=engine --cov-branch` from C:/dev/Omni-cov.

## UI (vitest) — measured, honest
792 tests green / 53 files. Statements/Lines 75.2%, Branches 88.92% (clears 85), Functions 81.06%.
Statement gap = WebGL/Canvas2D/Web-Audio rendering + entrypoints (browser boundaries, e2e-covered).

## Agent ledger (test-writing; each creates disjoint new tests/ files, no engine/ edits)
- T1 wiring settings validation + gateway/dispatcher
- T2 agents tools (free-slot/mapper/contacts/card builders)
- T3 index (vec store/embedder/watchdog/indexer/chunker/router/frontmatter)
- T4 naomi/voice (turn gateway/speaker/mic source/orchestrator/cartesia conn/dispatchers)
- T5 router provider clients (fake SDK) + provider_key_live_validation
- T6 google (oauth flow/session/gateway/token store)
- T7 stt (parakeet/vad fake model, weights/keep_audio/live_capture/capture_model_loading)
- T8 audio+detect (pyaudio backend/device listing/desktop snapshot/mic detector)
- T9 server + wiring dispatchers error paths
- T10 security redaction/dpapi + dictation session + ask dispatchers

## Candidate per-line pragma exclusions (apply ONLY if needed after measuring)
- engine/agents/approval_card_builder.py L148-150,174-176 — unreachable ValidationError except (inputs pre-bounded by _clean_str) (T2)
- engine/index/markdown_heading_aware_chunker.py L157 — unreachable defensive break (re.finditer endpos bounds match.end() <= end) (T3)
- engine/stt/live_capture_service.py L77-79 — _default_backend_factory imports real hw backend (T7) [may be coverable via a type-assert test — prefer test]
- dpapi_windows_crypto.py — NO exclusion: T10 covered platform guards+stub; 52-81 covered by round-trip suite on win32
- model_weights_downloader.py L270-275 __main__ — already handled by .coveragerc __main__ exclude
- dictation_session_service.py branch [155,161] — unreachable (begin() always sets _drain_task) (T10) — leave, may pragma if it blocks branch gate

## Agent completion status
T1✓ T2✓ T3✓ T5✓ T6✓ T7✓(50) T8✓(47) T10✓(26) | T4 running | T9 running

## Decisions
- Tooling ad-hoc via `uv run --with pytest-cov --with coverage` — NOT added to pyproject/uv.lock.
- Most "boundary" files lazy-import hw/net libs -> testable via sys.modules fake injection.
  Only truly un-fakeable lines (real torch/nemo load, real socket, real DPAPI/ctypes) get pragma'd.
