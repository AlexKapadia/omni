//! Live captions overlay: always-on-top frameless window at the bottom of the
//! primary monitor. Loads `captions.html` (separate Vite entry) and is shown
//! only while a capture session is live and the user has the overlay enabled.
//!
//! The overlay webview owns its own engine WebSocket (same pattern as the
//! dictation pill) — the main window only toggles visibility via
//! `set_captions_overlay_visible`.

use tauri::{AppHandle, Manager, PhysicalPosition, WebviewUrl, WebviewWindowBuilder};

/// Window label pinned by capabilities/captions-overlay.json.
pub const CAPTIONS_WINDOW_LABEL: &str = "captions";

const CAPTIONS_WIDTH: f64 = 720.0;
const CAPTIONS_HEIGHT: f64 = 140.0;
const CAPTIONS_BOTTOM_MARGIN: f64 = 32.0;

/// Create the (hidden) captions window up front — first show must be instant.
pub fn setup_captions_overlay(app: &AppHandle) -> tauri::Result<()> {
    if app.get_webview_window(CAPTIONS_WINDOW_LABEL).is_some() {
        return Ok(()); // idempotent (dev hot-restart safety)
    }
    WebviewWindowBuilder::new(
        app,
        CAPTIONS_WINDOW_LABEL,
        WebviewUrl::App("captions.html".into()),
    )
    .title("Omni Captions")
    .inner_size(CAPTIONS_WIDTH, CAPTIONS_HEIGHT)
    .decorations(false)
    .transparent(true)
    .always_on_top(true)
    .skip_taskbar(true)
    .resizable(false)
    .maximizable(false)
    .minimizable(false)
    .visible(false)
    .focused(false)
    .build()?;
    Ok(())
}

fn position_bottom_center(window: &tauri::WebviewWindow) {
    if let Ok(Some(monitor)) = window.current_monitor() {
        let size = monitor.size();
        let scale = monitor.scale_factor();
        let screen_w = size.width as f64 / scale;
        let screen_h = size.height as f64 / scale;
        let x = ((screen_w - CAPTIONS_WIDTH) / 2.0).max(0.0);
        let y = (screen_h - CAPTIONS_HEIGHT - CAPTIONS_BOTTOM_MARGIN).max(0.0);
        let _ = window.set_position(PhysicalPosition::new(x, y));
    }
}

/// Show or hide the captions overlay. Repositions on show so multi-monitor
/// changes are reflected.
#[tauri::command]
pub fn set_captions_overlay_visible(app: AppHandle, visible: bool) -> tauri::Result<()> {
    let window = match app.get_webview_window(CAPTIONS_WINDOW_LABEL) {
        Some(w) => w,
        None => {
            setup_captions_overlay(&app)?;
            app.get_webview_window(CAPTIONS_WINDOW_LABEL)
                .ok_or_else(|| tauri::Error::FailedToReceiveMessage)?
        }
    };
    if visible {
        position_bottom_center(&window);
        window.show()?;
    } else {
        window.hide()?;
    }
    Ok(())
}
