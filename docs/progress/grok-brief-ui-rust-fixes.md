You are fixing verified functional defects in a Tauri 2 + React desktop app (Omni). Two reviewed findings lists are your work orders — read BOTH files first:
- docs/progress/sweep-ui.md (11 items, UI + one new Rust command)
- docs/progress/sweep-rust-packaging.md (items 1,3,4,5,6,7,8,14,15 are the confirmed ones; skip REFUTED items)

Scope: apps/ui/src, apps/ui/src-tauri/src, apps/ui/src-tauri/tauri.conf.json, apps/ui/src-tauri/Cargo.toml, pyproject.toml. Do NOT run any git commands. Do NOT touch engine/*.py logic (pyproject.toml dependency move is allowed).

Fix ALL of these, with tests where the repo's patterns support them (vitest for TS; the repo pins behavior with small focused test files named <module>__<behaviour>.test.ts):

FROM sweep-ui.md — all 11 items. Key design decisions already made for you:
- Items 1+2+3+8 (meeting-toast) are ONE coherent redesign: the main window becomes the single source of truth. Pass the toast content (suggestion or stop-hint payload) through the Rust show command or a Tauri event emitted to the toast window; delete the overlay's own engine WebSocket (meeting-toast-engine-bridge.ts) if nothing else needs it; "Keep going" and "Dismiss" both notify the main window via Rust command -> event -> store update (clearStopHint / dismiss). Remove the lastVisible cache; always invoke set_meeting_toast_visible (idempotent). Update/extend the existing meeting-toast tests to pin the new contract.
- Item 4 (updater surface): add a small update section to the Settings screen: listens for updater:update-available (show version + "Install update" button), invokes updater_download_and_install with download-progress shown, then offers "Restart now" via updater_restart_app. Handle updater:error by showing a quiet non-blocking notice. Follow the existing settings section component patterns in src/components/settings/.
- Items 5+6 (pill window): fetch the configured hotkey over the pill's own dictation-engine-bridge socket (add a settings request path), and route card.updated frames into a pill-local cards store so Approve renders and card.approve is sent over sendDictationCommand.
- Item 7: perform the hotkey sync after the first successful engine status check (or a bounded retry loop matching the setup.status probe pattern).
- Item 9: delete the dead component AND its test.
- Item 11: change Record Inline to trigger the inline dictation recorder flow and update the pinning test to the new intent.

FROM sweep-rust-packaging.md:
- Item 1: change the updater endpoint in tauri.conf.json (and the matching packaging/README.md references) from AlexKapadia/omni to bhaskaraanjana/omni (the origin remote that will publish releases).
- Items 3+15: fix meeting_toast_window.rs and captions_overlay_window.rs positioning — copy the correct DPI math from dictation_pill_window.rs:244-257 (multiply logical constants by scale factor, add monitor.position() offset), and position relative to an explicitly chosen monitor (primary_monitor() per the doc comment) rather than current_monitor() of a hidden window.
- Item 4: harden reveal_path_in_explorer in lib.rs — canonicalize the path, require it to exist; if it is a directory open it, if it is a file use `explorer /select,<path>`; reject anything else with an error. Never pass a file path bare to explorer.exe.
- Item 5: in engine_sidecar.rs, detect repeated fast exits (N consecutive respawns where the child lived less than a few seconds) and emit a user-visible event (e.g. engine:unhealthy) to the main window so the UI can show something; keep the existing backoff.
- Item 6: put the spawned engine child in a Win32 Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so force-kill of the shell also kills the engine (windows-rs or winapi patterns; keep it Windows-gated with #[cfg(windows)]).
- Item 7: move httpx from the dev dependency group to [project].dependencies in pyproject.toml, and run `uv lock` to update the lockfile.
- Item 8: fix the stale Cargo.toml comment about the updater plugin.
- Item 14: remove the `httpx2` dev dependency (typosquat risk, nothing imports it) and re-lock.

HARD RULES:
- No @ts-ignore / any-casts / #[allow] silencing / weakened configs. Root-cause fixes only.
- Never weaken a security control. The reveal_path_in_explorer fix is a security control — fail closed.
- After all fixes, these must ALL pass (run them, iterate until green):
  1. cd apps/ui && npx tsc --noEmit
  2. cd apps/ui && npm run -s test
  3. cd apps/ui/src-tauri && cargo check
  4. uv lock --check || uv lock (lockfile consistent)
- Final message: list each finding number with one line on how it was fixed, then paste the final summary line of each verification command.