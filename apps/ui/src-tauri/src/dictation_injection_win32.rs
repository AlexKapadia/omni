//! Win32 implementation of the dictation paste: focus gate -> clipboard
//! save/set -> `SendInput` Ctrl+V -> settle -> restore.
//!
//! The blocking platform half of `dictation_text_injection` (which owns the
//! pure policy: chord order, target classification, honest messages). Every
//! failure path here states clipboard reality — after the dictation is
//! staged, failures always leave it one manual Ctrl+V away, never lost.

#[cfg(windows)]
mod platform {
    use std::time::{Duration, Instant};

    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, HWND};
    use windows_sys::Win32::Security::{
        GetTokenInformation, TokenElevation, TOKEN_ELEVATION, TOKEN_QUERY,
    };
    use windows_sys::Win32::System::Threading::{
        GetCurrentProcess, OpenProcess, OpenProcessToken, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetForegroundWindow, GetWindowThreadProcessId, IsWindow, SetForegroundWindow,
    };

    use crate::dictation_clipboard_win32::{
        read_clipboard_text, restore_clipboard_text, write_clipboard_text,
    };
    use crate::dictation_text_injection::{
        classify_target, failure_with_clipboard_note, paste_key_sequence, InjectionOutcome,
    };

    /// Paste consumers read the clipboard asynchronously after the Ctrl+V
    /// lands; restoring too early races them and pastes the OLD content.
    const PASTE_SETTLE_DELAY: Duration = Duration::from_millis(300);
    /// Small settle after a focus hand-off before sending keys.
    const FOCUS_SETTLE_DELAY: Duration = Duration::from_millis(30);

    fn ok(started: Instant) -> InjectionOutcome {
        InjectionOutcome {
            ok: true,
            elapsed_ms: started.elapsed().as_millis() as u64,
            failure_reason: None,
        }
    }

    fn fail(started: Instant, reason: String) -> InjectionOutcome {
        InjectionOutcome {
            ok: false,
            elapsed_ms: started.elapsed().as_millis() as u64,
            failure_reason: Some(reason),
        }
    }

    /// The full save -> set -> paste -> restore flow. Blocking; called from
    /// `spawn_blocking`. Every failure path is honest about clipboard state.
    pub fn perform_injection(text: &str, target_hwnd: i64) -> InjectionOutcome {
        let started = Instant::now();
        if text.is_empty() {
            return fail(started, "nothing to insert".to_string());
        }
        let target: HWND = target_hwnd as HWND;
        // SAFETY: IsWindow tolerates any value; that is its whole purpose.
        let window_valid = target != 0 && unsafe { IsWindow(target) } != 0;
        if let Err(reason) = classify_target(
            window_valid,
            window_process_is_elevated(target),
            current_process_is_elevated(),
        ) {
            // Blocked before touching focus: still leave the text one
            // manual paste away rather than losing it.
            return match write_clipboard_text(text) {
                Ok(()) => fail(started, failure_with_clipboard_note(reason)),
                Err(clip) => fail(started, format!("{reason}; clipboard also failed: {clip}")),
            };
        }
        // Focus contract: the pill never steals focus, so the keydown
        // target should still be foreground. If something else grabbed it,
        // try ONE polite hand-back; pasting into the wrong window is the
        // one unacceptable outcome.
        // SAFETY: reading the foreground window has no preconditions.
        if unsafe { GetForegroundWindow() } != target {
            // SAFETY: best-effort; failure is detected by the recheck below.
            unsafe { SetForegroundWindow(target) };
            std::thread::sleep(FOCUS_SETTLE_DELAY);
            // SAFETY: as above.
            if unsafe { GetForegroundWindow() } != target {
                return match write_clipboard_text(text) {
                    Ok(()) => fail(
                        started,
                        failure_with_clipboard_note("the target window lost focus"),
                    ),
                    Err(clip) => fail(started, format!("focus lost; clipboard failed: {clip}")),
                };
            }
        }
        let saved = match read_clipboard_text() {
            Ok(saved) => saved,
            Err(reason) => return fail(started, format!("could not save clipboard: {reason}")),
        };
        if let Err(reason) = write_clipboard_text(text) {
            return fail(started, format!("could not stage the text: {reason}"));
        }
        if let Err(reason) = send_paste_chord() {
            // The chord did not go through — leave the dictation staged so
            // a manual Ctrl+V still works (never restore over it).
            return fail(started, failure_with_clipboard_note(&reason));
        }
        std::thread::sleep(PASTE_SETTLE_DELAY); // let the app read the clipboard
        if let Err(reason) = restore_clipboard_text(saved.as_deref()) {
            // The paste DID land; only the restore failed — report success
            // with the caveat carried honestly in the reason field.
            return InjectionOutcome {
                ok: true,
                elapsed_ms: started.elapsed().as_millis() as u64,
                failure_reason: Some(format!("inserted, but clipboard restore failed: {reason}")),
            };
        }
        ok(started)
    }

    /// Synthesize the Ctrl+V chord; error when Windows rejects any event
    /// (0 injected == blocked, e.g. UIPI edge the gate could not classify).
    fn send_paste_chord() -> Result<(), String> {
        let inputs: Vec<INPUT> = paste_key_sequence()
            .iter()
            .map(|&(vk, up)| INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: vk,
                        wScan: 0,
                        dwFlags: if up { KEYEVENTF_KEYUP } else { 0 },
                        time: 0,
                        dwExtraInfo: 0,
                    },
                },
            })
            .collect();
        // SAFETY: `inputs` is a valid, correctly-sized INPUT array.
        let sent = unsafe {
            SendInput(
                inputs.len() as u32,
                inputs.as_ptr(),
                std::mem::size_of::<INPUT>() as i32,
            )
        };
        if sent != inputs.len() as u32 {
            return Err(format!(
                "Windows blocked the paste keystrokes ({sent}/{} sent)",
                inputs.len()
            ));
        }
        Ok(())
    }

    /// Is the process owning `hwnd` elevated? `None` when unknowable
    /// (access denied etc.) — the caller proceeds and lets the send decide.
    fn window_process_is_elevated(hwnd: HWND) -> Option<bool> {
        let mut process_id: u32 = 0;
        // SAFETY: out-param write of a u32; hwnd validity already checked.
        unsafe { GetWindowThreadProcessId(hwnd, &mut process_id) };
        if process_id == 0 {
            return None;
        }
        // SAFETY: least-privilege query handle; closed below on all paths.
        let process = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, process_id) };
        if process == 0 {
            return None;
        }
        let elevated = process_token_is_elevated(process);
        // SAFETY: pairs the successful OpenProcess.
        unsafe { CloseHandle(process) };
        elevated
    }

    fn current_process_is_elevated() -> bool {
        // SAFETY: pseudo-handle; needs no CloseHandle.
        process_token_is_elevated(unsafe { GetCurrentProcess() }).unwrap_or(false)
    }

    fn process_token_is_elevated(process: HANDLE) -> Option<bool> {
        let mut token: HANDLE = 0;
        // SAFETY: out-param handle; closed below on the success path.
        if unsafe { OpenProcessToken(process, TOKEN_QUERY, &mut token) } == 0 {
            return None;
        }
        let mut elevation = TOKEN_ELEVATION { TokenIsElevated: 0 };
        let mut returned: u32 = 0;
        // SAFETY: buffer is exactly TOKEN_ELEVATION-sized, as declared.
        let queried = unsafe {
            GetTokenInformation(
                token,
                TokenElevation,
                &mut elevation as *mut TOKEN_ELEVATION as *mut core::ffi::c_void,
                std::mem::size_of::<TOKEN_ELEVATION>() as u32,
                &mut returned,
            )
        };
        // SAFETY: pairs the successful OpenProcessToken.
        unsafe { CloseHandle(token) };
        if queried == 0 {
            return None;
        }
        Some(elevation.TokenIsElevated != 0)
    }
}

#[cfg(windows)]
pub use platform::perform_injection;

/// Non-Windows build: injection honestly unavailable (Omni ships on
/// Windows; this keeps cross-platform checks compiling).
#[cfg(not(windows))]
pub fn perform_injection(
    _text: &str,
    _target_hwnd: i64,
) -> crate::dictation_text_injection::InjectionOutcome {
    crate::dictation_text_injection::InjectionOutcome {
        ok: false,
        elapsed_ms: 0,
        failure_reason: Some("text injection is only available on Windows".to_string()),
    }
}
