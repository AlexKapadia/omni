//! Universal dictation text injection: cleaned text -> the focused app.
//!
//! The Wispr-Flow-beating paste path: save the user's clipboard text, set
//! the cleaned dictation, synthesize Ctrl+V with `SendInput` into the
//! window captured at KEYDOWN, wait for paste consumers to read, then
//! restore the clipboard. Exposed to the pill webview as the
//! `inject_dictation_text` Tauri command (see `dictation-engine-bridge.ts`).
//! This module owns the PURE policy (chord order, target gate, honest
//! messages) + the command; the Win32 legwork lives in
//! `dictation_injection_win32`, the clipboard in `dictation_clipboard_win32`.
//!
//! Known edge cases, handled HONESTLY (never silently):
//! - Elevated (admin) target + non-elevated Omni: UIPI blocks synthetic
//!   input — detected up front, reported, text left on the clipboard so a
//!   manual Ctrl+V still lands it.
//! - Target window gone / focus moved elsewhere: refused (pasting into the
//!   wrong window would be worse than failing), text left on the clipboard.
//! - Apps that IGNORE synthetic Ctrl+V (some games, secure fields): the
//!   keystroke send succeeds but nothing lands — undetectable from here;
//!   documented as the residual honesty gap.
//! - Clipboard managers may capture the transient text; non-text clipboard
//!   content is not preserved (see `dictation_clipboard_win32`).

use serde::Serialize;

/// What the pill receives — mirrors `InjectionOutcome` in the bridge.
#[derive(Clone, Serialize)]
pub struct InjectionOutcome {
    pub ok: bool,
    /// Real measured wall-clock ms for the whole injection leg.
    pub elapsed_ms: u64,
    /// Honest, plain-voice reason when `ok` is false (or a success caveat).
    pub failure_reason: Option<String>,
}

/// Virtual-key codes for the paste chord (winuser.h). Named here so the
/// pure sequence builder is testable without the windows crate.
pub const VK_CONTROL_CODE: u16 = 0x11;
pub const VK_V_CODE: u16 = 0x56;

/// One synthetic key event: (virtual key, is_key_up).
pub type KeyStep = (u16, bool);

/// The exact Ctrl+V chord, in press/release order. Pure — unit-tested:
/// a wrong order (V before Ctrl, or a stuck Ctrl) types "v" into the
/// user's document or poisons their modifier state.
pub fn paste_key_sequence() -> [KeyStep; 4] {
    [
        (VK_CONTROL_CODE, false), // Ctrl down
        (VK_V_CODE, false),       // V down
        (VK_V_CODE, true),        // V up
        (VK_CONTROL_CODE, true),  // Ctrl up — ALWAYS released last
    ]
}

/// Pure fail-closed target gate (unit-tested): decides whether the paste
/// may proceed given what we could observe about the target window.
pub fn classify_target(
    window_valid: bool,
    target_elevated: Option<bool>,
    we_elevated: bool,
) -> Result<(), &'static str> {
    if !window_valid {
        return Err("the target window is gone");
    }
    // UIPI: a non-elevated process cannot send input to an elevated one.
    // `None` (elevation unknown) proceeds — the send itself will tell.
    if target_elevated == Some(true) && !we_elevated {
        return Err("the target app runs elevated (admin) — Windows blocks pasting into it");
    }
    Ok(())
}

/// Compose the honest failure message: after the clipboard already carries
/// the dictation, every failure path must say the words are one Ctrl+V away.
pub fn failure_with_clipboard_note(reason: &str) -> String {
    format!("{reason}; your text is on the clipboard — press Ctrl+V to insert it manually")
}

/// Async command: the blocking Win32 work (clipboard contention, the paste
/// settle delay) runs off the IPC thread.
#[tauri::command]
pub async fn inject_dictation_text(text: String, target_hwnd: i64) -> InjectionOutcome {
    tauri::async_runtime::spawn_blocking(move || {
        crate::dictation_injection_win32::perform_injection(&text, target_hwnd)
    })
    .await
    .unwrap_or_else(|join_error| InjectionOutcome {
        ok: false,
        elapsed_ms: 0,
        failure_reason: Some(format!("injection task failed: {join_error}")),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paste_chord_is_ctrl_down_v_down_v_up_ctrl_up() {
        // Exact order pinned: any deviation types "v" or wedges Ctrl.
        assert_eq!(
            paste_key_sequence(),
            [
                (VK_CONTROL_CODE, false),
                (VK_V_CODE, false),
                (VK_V_CODE, true),
                (VK_CONTROL_CODE, true),
            ]
        );
    }

    #[test]
    fn paste_chord_releases_everything_it_presses() {
        // No stuck modifiers: every key pressed is released, in LIFO order.
        let sequence = paste_key_sequence();
        let mut held: Vec<u16> = Vec::new();
        for (vk, up) in sequence {
            if up {
                assert_eq!(held.pop(), Some(vk), "released key must be the last held");
            } else {
                held.push(vk);
            }
        }
        assert!(held.is_empty(), "a stuck key would poison the user's session");
    }

    #[test]
    fn invalid_window_is_refused() {
        assert_eq!(classify_target(false, None, false), Err("the target window is gone"));
        // Even a supposedly-elevated-but-gone window is refused for absence.
        assert!(classify_target(false, Some(true), true).is_err());
    }

    #[test]
    fn elevated_target_from_unelevated_omni_is_refused() {
        let result = classify_target(true, Some(true), false);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("elevated"));
    }

    #[test]
    fn elevated_target_from_elevated_omni_proceeds() {
        assert_eq!(classify_target(true, Some(true), true), Ok(()));
    }

    #[test]
    fn unknown_elevation_proceeds_and_lets_the_send_decide() {
        assert_eq!(classify_target(true, None, false), Ok(()));
    }

    #[test]
    fn normal_target_proceeds() {
        assert_eq!(classify_target(true, Some(false), false), Ok(()));
    }

    #[test]
    fn clipboard_note_names_the_manual_escape_hatch() {
        let message = failure_with_clipboard_note("focus lost");
        assert!(message.starts_with("focus lost"));
        assert!(message.contains("press Ctrl+V")); // the words are never lost
    }
}
