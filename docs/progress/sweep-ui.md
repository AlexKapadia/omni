# Fable UI sweep — confirmed findings (2026-07-17)

1. MAJOR — meeting-toast-view.tsx:91-100 + wire-meeting-toast-desktop.ts:34-40,57-65 — "Keep going" clears stopHintReason only in the overlay-local store and hides the window directly, never telling the main window; meetingDetectionStore.stopHintReason stays non-null and lastVisible stays true, so every later capture.suggest_stop in the same capture is silently invisible. Fix: "Keep going" invokes a new meeting_toast_keep_going Rust command that emits an event the main window handles with clearStopHint, mirroring the dismiss path.

2. MAJOR — wire-meeting-toast-desktop.ts:55-65 + meeting_toast_window.rs:85-111 — lastVisible dedupe assumes main window is the only visibility driver, but all three Rust toast commands hide the window themselves; state can desync so the toast never re-shows. Fix: drop the lastVisible cache and always invoke set_meeting_toast_visible on each sync (command is idempotent).

3. MAJOR — meeting-toast-engine-bridge.ts:19-38,68-76 + meeting-toast-view.tsx:24-29 — visibility driven by main window's store but content by the overlay's own WebSocket; while overlay socket is down the shown toast renders an empty shell, and a missed capture.started shows a stale "Start capture" card instead of the stop hint. Fix: pass the suggestion/stop-hint payload from the main window through the show command (or a Tauri event) so one socket is the single source of truth; the overlay's own WS becomes unnecessary — remove it if nothing else needs it.

4. MAJOR — updater_launch_check.rs emits updater:checking/update-available/download-progress/installed/error and registers updater_download_and_install / updater_restart_app, but NO UI file listens or invokes either — no working update path. Fix: add a Settings surface that listens for updater:update-available, invokes updater_download_and_install with progress, then offers updater_restart_app.

5. MAJOR — pill/pill-main.tsx:22-27 — getSettings() routes through the lib-level live-engine-socket which is never started in the pill webview, so it always rejects and the idle hint is permanently "Hold F9" even after rebinding. Fix: fetch the hotkey over the pill's own connection (settings request path in dictation-engine-bridge) or pass the label from Rust with the hold event.

6. MAJOR — pill/dictation-pill-view.tsx:14,228-239,253-262 — Approve button depends on approvalCardsStore which is never populated in the pill webview (bridge ignores card.updated), so Approve never renders; approveCard would no-op anyway (no lib socket). Fix: route card.updated frames from the pill's own socket into a local cards store and send card.approve over sendDictationCommand.

7. MAJOR — App.tsx:63-64 + sync-dictation-hotkey.ts:37-45 — syncConfiguredDictationHotkey fires while the WS is still connecting; sendEnvelope returns false, rejection swallowed, no retry — custom push-to-talk key not applied on cold boot. Fix: retry with the same bounded loop the setup.status probe uses, or run after first successful checkStatus.

8. MINOR — wire-meeting-toast-desktop.ts:22-28 — applyVisibility flips lastVisible before the invoke and discards failures; commit lastVisible only after the invoke resolves, revert in catch. (Subsumed by fix 2 if cache is removed.)

9. MINOR — components/live/meeting-detected-toast.tsx — dead code after desktop-toast move (only its own test references it). Delete component + its unit test in the same change.

10. MINOR — App.tsx:162-183 — unwireMeetingToast/unlistenTray assigned inside async IIFE; cleanup before import resolves leaks listeners (dev double-mount fires requestCaptureStart twice). Fix: cancelled flag in cleanup; unwire immediately if already cancelled.

11. MINOR — home-screen.tsx:167-169 — "Record Inline" on the Keyboard Voice Replacement card starts a full meeting capture instead of the inline dictation recorder; pinning test home-screen__record-inline-starts-capture.test.tsx asserts current behavior. Fix: navigate to dictation screen and trigger its inline recorder; update the pinning test to assert the new intent.

Refuted: overlay rearm churn is benign (dismiss cooldown honored); no envelope/event name mismatches (23 checked); no orphaned wiring modules; no dead controls beyond the above.
