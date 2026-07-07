# Coverage Hardening — Progress Tracker — ✅ COMPLETE

## RESULT (authoritative, full suite green)
- LINE:   87.49% → **98.87%** (9491/9599)  — PASS (≥90)
- BRANCH: 76.31% → **94.74%** (1908/2014) — PASS (≥85)
- 1974 tests total (1 live_stt deselected); +408 new adversarial test fns across 27 files.
- ruff + mypy(strict) clean; coverage tooling ad-hoc only (absent from pyproject/uv.lock).
- No per-line pragmas added; gate met with genuine tests + .coveragerc standard exclusions.

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
- [x] T3 index (36 tests; flagged markdown chunker L157 unreachable)
- [x] T4 naomi/voice (40 tests; real-model/hw boundaries noted, not excluded — gate met)
- [x] T5 router provider clients + provider_key_live_validation (30 tests, 0 new excl)
- [x] T6 google (oauth flow, session, gateway, token store) (32 tests, 0 excl — real loopback)
- [x] T7 stt (50 tests; boundaries handled by config __main__ exclude)
- [x] T8 audio+detect (47 tests; pyaudio backend 0%→full, 0 excl)
- [x] T9 server + wiring dispatchers (43 tests; integration-only closures noted)
- [x] Add coverage config (.coveragerc) — omit live probe + standard exclude_lines only
- [x] Consolidated coverage re-run: line 98.87 / branch 94.74 — PASS
- [x] ruff + mypy(strict) clean on new tests; full suite green (1974 tests)
- [x] evidence/coverage-report.md documenting final numbers + exclusions
- [x] Commit + push feature/coverage-hardening

## Resume here
DONE — nothing left. Gate met (line 98.87 / branch 94.74), suite green, ruff+mypy clean,
tooling ad-hoc, evidence report written. Branch feature/coverage-hardening pushed.

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
