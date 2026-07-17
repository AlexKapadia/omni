You are fixing 13 verified runtime defects in the Python engine of the Omni desktop app. The reviewed findings list is your work order — read docs/progress/sweep-engine.md first (13 items with file:line and prescribed fixes).

Scope: engine/ and tests/ ONLY. Do NOT run any git commands. Do NOT touch apps/ui/, pyproject.toml, or docs/ (read-only). Another agent is concurrently editing apps/ui/ — ignore any changes you see there.

Set PYTHONUTF8=1 and PYTHONIOENCODING=utf-8 for every command (Windows cp1252 console).

Work through ALL 13 items. Priorities and notes:
- Item 1 is a SECURITY BLOCKER (kill-switch bypass in the Microsoft Graph surface). Mirror the Google gateway's kill-switch refusal exactly (see engine/google/google_api_gateway.py:36-39) at every Graph call site and in MicrosoftSession.request_json and the token refresh. Fail closed. Add an inline comment naming the control (e.g. "# kill-switch: refuse all egress when engaged"). Write a regression test that engages the kill switch and asserts the Graph gateway refuses (mirror however the Google gateway's kill-switch tests are structured — find them in tests/).
- Items 2+3 are one coherent change to the rearm path: rearm on the hub's 0->1 subscriber transition rather than every connect, and prevent rearm from resurrecting auto-start for sessions the user manually stopped (per-source cooldown or excluding auto-start-eligible sources). Read engine/detect/auto_start_rules_engine.py and detection_service.py carefully first; there are existing tests in tests/test_detect__*.py — extend them to pin the new behavior (reconnect does not duplicate meeting.detected; manual stop then reconnect does not auto-restart capture).
- Items 4+13 are one change: a shared asyncio.Lock serializing start()/stop() in live_capture_service.py, with stop()'s state-nulling in a finally. Add a test for the double-start race (two concurrent starts -> one meeting) and double-stop.
- Item 5: per-provider dedupe in calendar_poll_service. Test: both providers connected, second tick re-broadcasts nothing.
- Item 6: one-line asyncio.to_thread fix. Test if cheap; otherwise rely on existing suite.
- Item 7: threading.Event cancellation flag threaded into the download loop, checked per block; single-flight guard held until the worker thread exits. Test with a fake fetch loop.
- Item 8: run meeting.finalize, meeting.retranscribe, and import.media handlers in spawned tasks so the receive loop keeps draining; the reply envelope is sent on completion. Keep task references (no GC'd tasks). Make sure errors still produce error replies. Extend an existing wiring test to prove a second command is processed while a long command is in flight.
- Items 9-12: small lifecycle fixes exactly as prescribed in the findings file.

HARD RULES:
- No behavior-weakening: never disable a security control, never widen a permission. Fail closed everywhere.
- No `# noqa` / `# type: ignore` unless genuinely unavoidable with an inline justification.
- Every fix that changes observable behavior gets a test (repo pattern: tests/test_<area>__<behaviour>.py, no network, synthetic fixtures).
- After all fixes, ALL of these must pass from the repo root — run them and iterate until green:
  1. uv run pytest -q
  2. uv run ruff check .
  3. uv run mypy
- Final message: list each finding number with one line on the fix + test added, then paste the final summary line of each of the three commands.