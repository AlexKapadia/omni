You are fixing lint and type errors in the Python engine of this repo. Work ONLY on files under engine/ and tests/. Do NOT run any git commands. Do NOT touch apps/ui/ or docs/ (except you may READ anything).

Set these env vars for every command you run: PYTHONUTF8=1, PYTHONIOENCODING=utf-8 (Windows cp1252 console crashes otherwise).

GOAL — all three commands exit 0, run from the repo root:
1. `uv run ruff check .`  (currently 50 errors; concise inventory in docs/progress/gate-ruff-errors.txt, but re-run for live state since 53 were already auto-fixed)
2. `uv run mypy`  (currently 90 errors in 43 files; inventory in docs/progress/gate-mypy-errors.txt)
3. `uv run pytest -q`  (currently fully green ~2300 tests — MUST stay green; note unused-import auto-fixes were already applied, so verify nothing broke)

PRIORITY BUG: engine/wiring/speaker_enroll_command_dispatcher.py:61 has F821 Undefined name `Path` — a real latent crash. Add the missing import and check the surrounding code path actually works; if there is a test gap that let this slip, add one small targeted test.

Known error classes:
- ruff: E501 long lines (wrap), F841 unused locals, RUF043 unescaped regex metacharacters in pytest.raises match=, remaining F401s.
- mypy: missing annotations in test functions (annotate properly, `-> None` for tests, real types for fixtures/params); `Row | None` indexing in tests\test_enhance__meeting_delete.py (assert row is not None before indexing); engine/protocol not explicitly re-exporting MeetingTextReplacePayload / MeetingExportCommandPayload / TranscriptSegmentUpdatePayload (add them to the explicit re-export/__all__ in engine/protocol the same way other payloads are exported); dict invariance at engine/enhance/meeting_command_dispatcher.py:398 (type the local as dict[str, object] or use Mapping); fake router protocol mismatches in tests (make the fakes' route() signature match CompletionRouterProtocol exactly); missing return annotations in engine/wiring/server_default_service_factories.py:170,178; engine/cli_app.py:143 no-any-return (cast or narrow properly).

HARD RULES:
- NO `# noqa`, `# type: ignore`, or weakening pyproject.toml ruff/mypy config. Fix root causes. (If you hit a genuinely unfixable third-party stub gap, a narrowly-scoped `# type: ignore[specific-code]` with an inline justification comment is the last resort — expect zero or near-zero of these.)
- NO behavior changes to engine code beyond the Path import fix; everything else is annotation/lint-level repair.
- Iterate: fix, re-run all three commands, repeat until all green.
- Final message: paste the final summary line of each of the three commands.