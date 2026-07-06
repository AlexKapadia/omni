//! Hold-to-dictate: global F9 hold -> frameless "pill" overlay window.
//!
//! Owns the M5 shell surface: registers the hold-key global shortcut,
//! creates the always-on-top transparent pill window (loads `pill.html`,
//! a separate Vite entry), positions it bottom-center of the current
//! monitor, and relays key state to it as Tauri events. Everything
//! intelligent (mic capture, STT, mode split) lives in the Python engine —
//! the pill webview talks to it over the same loopback WebSocket as the
//! main window.
//!
//! Event contract with `apps/ui/src/pill/`:
//! - `dictation-hold-pressed`  — key went down (pill shows + begins); its
//!   payload carries the KEYDOWN-captured foreground window (`target_hwnd`)
//!   and whether it is an external app (`inject_eligible`) — the injection
//!   target is decided at keydown, never at release (focus contract).
//! - `dictation-hold-released` — key came up (pill ends the session)
//! The pill window hides ITSELF once its result popover is dismissed. It
//! is created unfocused and never steals focus — the user keeps typing
//! wherever they were.

use std::sync::atomic::{AtomicBool, Ordering};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

/// The push-to-talk hold key. One configurable constant — Settings-driven
/// rebinding is a later milestone and will feed this same registration.
pub const DICTATION_HOLD_KEY: &str = "F9";

/// Window label the capability file and the pill webview both pin.
pub const PILL_WINDOW_LABEL: &str = "pill";

// Logical window size. The visible pill row is ~44px (design §07); the
// WINDOW is taller and fully transparent so the 320px-wide result popover
// (label + quote + title + buttons, ~200px) can rise below the pill
// without clipping. Nothing paints outside the pill/popover surfaces.
const PILL_WIDTH: f64 = 420.0;
const PILL_HEIGHT: f64 = 300.0;
const PILL_BOTTOM_MARGIN: f64 = 48.0;

// Event names mirrored in apps/ui/src/pill/dictation-engine-bridge.ts.
const EVENT_HOLD_PRESSED: &str = "dictation-hold-pressed";
const EVENT_HOLD_RELEASED: &str = "dictation-hold-released";

/// Windows key auto-repeat fires repeated Pressed events while F9 is held;
/// only the FIRST press may show the pill and start a session.
static HOLD_ACTIVE: AtomicBool = AtomicBool::new(false);

/// Payload of `dictation-hold-pressed` (mirrored fail-closed by
/// `parseHoldPressedPayload` in dictation-engine-bridge.ts).
#[derive(Clone, Serialize)]
struct HoldPressedPayload {
    /// True when an EXTERNAL app owned focus at keydown — the default
    /// disposition is then INJECT (paste into that app on release).
    inject_eligible: bool,
    /// The keydown foreground window, as an integer handle for the bridge.
    target_hwnd: i64,
}

/// Snapshot the foreground window AT KEYDOWN. Eligible only when it is a
/// real window that is not one of Omni's own (dictating into Omni's main
/// window stays on the note path — deny by default).
fn capture_injection_target(app: &AppHandle) -> HoldPressedPayload {
    #[cfg(windows)]
    {
        // SAFETY: reading the foreground window has no preconditions.
        let foreground =
            unsafe { windows_sys::Win32::UI::WindowsAndMessaging::GetForegroundWindow() };
        if foreground == 0 {
            return HoldPressedPayload { inject_eligible: false, target_hwnd: 0 };
        }
        let ours = app.webview_windows().values().any(|window| {
            window
                .hwnd()
                .map(|handle| handle.0 as isize == foreground)
                .unwrap_or(false)
        });
        return HoldPressedPayload {
            inject_eligible: !ours,
            target_hwnd: foreground as i64,
        };
    }
    #[cfg(not(windows))]
    {
        let _ = app; // injection is Windows-only; note mode everywhere else
        HoldPressedPayload { inject_eligible: false, target_hwnd: 0 }
    }
}

/// Create the (hidden) pill window and bind the hold shortcut.
/// Called once from the app `setup` hook.
pub fn setup_dictation_pill(app: &AppHandle) -> tauri::Result<()> {
    create_pill_window(app)?;
    register_hold_shortcut(app)?;
    Ok(())
}

/// Build the pill window up front, hidden — the first keypress must show
/// it instantly, not pay webview cold-start latency.
fn create_pill_window(app: &AppHandle) -> tauri::Result<()> {
    if app.get_webview_window(PILL_WINDOW_LABEL).is_some() {
        return Ok(()); // idempotent (dev hot-restart safety)
    }
    WebviewWindowBuilder::new(app, PILL_WINDOW_LABEL, WebviewUrl::App("pill.html".into()))
        .title("Omni Dictation")
        .inner_size(PILL_WIDTH, PILL_HEIGHT)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .visible(false)
        // Never steal focus: the user is dictating over whatever app they
        // are in; the engine owns the mic, the pill only displays state.
        .focused(false)
        .build()?;
    Ok(())
}

/// Bind the hold key with a Pressed/Released handler (repeat-guarded).
fn register_hold_shortcut(app: &AppHandle) -> tauri::Result<()> {
    app.global_shortcut()
        .on_shortcut(DICTATION_HOLD_KEY, |app, _shortcut, event| {
            match event.state() {
                ShortcutState::Pressed => {
                    // Auto-repeat guard: only the first press acts.
                    if !HOLD_ACTIVE.swap(true, Ordering::SeqCst) {
                        // Capture the target BEFORE showing the pill: the
                        // pill is unfocused, but the order still guarantees
                        // the user's window is what gets snapshotted.
                        let payload = capture_injection_target(app);
                        show_pill_and_emit(app, EVENT_HOLD_PRESSED, payload);
                    }
                }
                ShortcutState::Released => {
                    if HOLD_ACTIVE.swap(false, Ordering::SeqCst) {
                        emit_to_pill(app, EVENT_HOLD_RELEASED);
                    }
                }
            }
        })
        .map_err(|e| tauri::Error::Anyhow(e.into()))?;
    Ok(())
}

fn show_pill_and_emit(app: &AppHandle, event: &str, payload: HoldPressedPayload) {
    if let Some(window) = app.get_webview_window(PILL_WINDOW_LABEL) {
        position_bottom_center(&window);
        // Best-effort: a failed show must not poison the shortcut handler —
        // the engine session is driven by the events, not by visibility.
        let _ = window.show();
        let _ = window.emit(event, payload);
    }
}

fn emit_to_pill(app: &AppHandle, event: &str) {
    if let Some(window) = app.get_webview_window(PILL_WINDOW_LABEL) {
        let _ = window.emit(event, ());
    }
}

/// Bottom-center of the pill's current monitor, DPI-aware.
fn position_bottom_center(window: &tauri::WebviewWindow) {
    let Ok(Some(monitor)) = window.current_monitor() else {
        return; // no monitor info: keep whatever position we have
    };
    let scale = monitor.scale_factor();
    let monitor_size = monitor.size();
    let width = (PILL_WIDTH * scale) as i32;
    let height = (PILL_HEIGHT * scale) as i32;
    let x = monitor.position().x + (monitor_size.width as i32 - width) / 2;
    let y = monitor.position().y + monitor_size.height as i32
        - height
        - (PILL_BOTTOM_MARGIN * scale) as i32;
    let _ = window.set_position(PhysicalPosition::new(x, y));
}
