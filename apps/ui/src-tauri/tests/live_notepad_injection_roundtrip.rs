//! LIVE injection round-trip against a real Notepad window.
//!
//! Ignored by default (drives the real desktop). Run explicitly:
//! `cargo test --test live_notepad_injection_roundtrip -- --ignored --nocapture`
//!
//! Flow: stage a sentinel on the clipboard -> spawn Notepad (foreground) ->
//! `perform_injection` (the REAL product path: clipboard-swap + SendInput
//! Ctrl+V + restore) -> assert the sentinel was restored -> read the text
//! BACK out of Notepad programmatically (Ctrl+A, Ctrl+C, read clipboard) ->
//! kill Notepad without saving. No mock at any step.

#![cfg(windows)]

use std::process::Command;
use std::thread::sleep;
use std::time::Duration;

use omni_ui_lib::dictation_clipboard_win32::{read_clipboard_text, write_clipboard_text};
use omni_ui_lib::dictation_injection_win32::perform_injection;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowTextW};

const SENTINEL: &str = "OMNI-SAVED-CLIPBOARD-SENTINEL";
const INJECTED: &str = "Can you send the report to Sanjay by Friday.";

fn send_chord(keys: &[(u16, bool)]) {
    let inputs: Vec<INPUT> = keys
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
    // SAFETY: valid INPUT array, exactly as in the product path.
    let sent =
        unsafe { SendInput(inputs.len() as u32, inputs.as_ptr(), size_of::<INPUT>() as i32) };
    assert_eq!(sent, inputs.len() as u32, "read-back chord was blocked");
}

fn foreground_title() -> String {
    // SAFETY: plain reads; buffer sized and truncated by the returned length.
    unsafe {
        let hwnd = GetForegroundWindow();
        let mut buffer = [0u16; 256];
        let length = GetWindowTextW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32);
        String::from_utf16_lossy(&buffer[..length.max(0) as usize])
    }
}

#[test]
#[ignore = "live: drives a real Notepad window on the desktop"]
fn injects_into_real_notepad_and_reads_it_back() {
    // 1. Stage the sentinel: proves the product restores the user's clipboard.
    write_clipboard_text(SENTINEL).expect("stage sentinel");

    // 2. Real Notepad, which takes foreground on launch.
    Command::new("notepad.exe").spawn().expect("spawn notepad");
    sleep(Duration::from_millis(2500));
    let title = foreground_title();
    assert!(
        title.to_lowercase().contains("notepad"),
        "foreground is {title:?}, not Notepad — aborting rather than pasting elsewhere"
    );
    // SAFETY: plain read.
    let target = unsafe { GetForegroundWindow() };

    // 3. THE PRODUCT PATH: clipboard-swap + Ctrl+V + settle + restore.
    let outcome = perform_injection(INJECTED, target as i64);
    println!(
        "perform_injection -> ok={} elapsed_ms={} reason={:?}",
        outcome.ok, outcome.elapsed_ms, outcome.failure_reason
    );
    assert!(outcome.ok, "injection failed: {:?}", outcome.failure_reason);

    // 4. Clipboard restored to the user's content (privacy + courtesy).
    let restored = read_clipboard_text().expect("read clipboard");
    assert_eq!(restored.as_deref(), Some(SENTINEL), "clipboard was not restored");

    // 5. Read the text back OUT of Notepad: select-all + copy, then read.
    const VK_CONTROL: u16 = 0x11;
    const VK_A: u16 = 0x41;
    const VK_C: u16 = 0x43;
    send_chord(&[(VK_CONTROL, false), (VK_A, false), (VK_A, true), (VK_CONTROL, true)]);
    sleep(Duration::from_millis(150));
    send_chord(&[(VK_CONTROL, false), (VK_C, false), (VK_C, true), (VK_CONTROL, true)]);
    sleep(Duration::from_millis(400));
    let read_back = read_clipboard_text().expect("read back").unwrap_or_default();
    println!("read back from Notepad: {read_back:?}");

    // 6. Close Notepad WITHOUT saving (kill discards the unsaved buffer).
    let _ = Command::new("taskkill").args(["/F", "/IM", "notepad.exe"]).status();
    // Leave the user's clipboard clean of test artifacts.
    let _ = write_clipboard_text("");

    assert_eq!(
        read_back.trim(),
        INJECTED,
        "the injected text did not land in Notepad"
    );
}
