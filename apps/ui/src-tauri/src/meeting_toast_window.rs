//! Desktop meeting-detected toast: always-on-top frameless window at the
//! bottom-right of the primary monitor. Loads `meeting-toast.html` (separate
//! Vite entry). Visibility is driven from the main window; Start / Not now
//! come back as shell commands that focus the main window and emit events.

use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewUrl, WebviewWindowBuilder};

/// Window label pinned by capabilities/meeting-toast.json.
pub const MEETING_TOAST_WINDOW_LABEL: &str = "meeting-toast";

const TOAST_WIDTH: f64 = 380.0;
const TOAST_HEIGHT: f64 = 168.0;
const TOAST_RIGHT_MARGIN: f64 = 24.0;
const TOAST_BOTTOM_MARGIN: f64 = 28.0;

/// Create the (hidden) toast window up front — first show must be instant.
pub fn setup_meeting_toast(app: &AppHandle) -> tauri::Result<()> {
    if app.get_webview_window(MEETING_TOAST_WINDOW_LABEL).is_some() {
        return Ok(()); // idempotent (dev hot-restart safety)
    }
    WebviewWindowBuilder::new(
        app,
        MEETING_TOAST_WINDOW_LABEL,
        WebviewUrl::App("meeting-toast.html".into()),
    )
    .title("Omni Steroid Meeting")
    .inner_size(TOAST_WIDTH, TOAST_HEIGHT)
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

fn position_bottom_right(window: &tauri::WebviewWindow) {
    if let Ok(Some(monitor)) = window.current_monitor() {
        let size = monitor.size();
        let scale = monitor.scale_factor();
        let screen_w = size.width as f64 / scale;
        let screen_h = size.height as f64 / scale;
        let x = (screen_w - TOAST_WIDTH - TOAST_RIGHT_MARGIN).max(0.0);
        let y = (screen_h - TOAST_HEIGHT - TOAST_BOTTOM_MARGIN).max(0.0);
        let _ = window.set_position(PhysicalPosition::new(x, y));
    }
}

fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// Show or hide the desktop meeting toast. Repositions on show.
#[tauri::command]
pub fn set_meeting_toast_visible(app: AppHandle, visible: bool) -> tauri::Result<()> {
    let window = match app.get_webview_window(MEETING_TOAST_WINDOW_LABEL) {
        Some(w) => w,
        None => {
            setup_meeting_toast(&app)?;
            app.get_webview_window(MEETING_TOAST_WINDOW_LABEL)
                .ok_or_else(|| tauri::Error::FailedToReceiveMessage)?
        }
    };
    if visible {
        position_bottom_right(&window);
        window.show()?;
        // Buttons need focus; steal briefly so Start / Not now work over Zoom.
        let _ = window.set_focus();
    } else {
        window.hide()?;
    }
    Ok(())
}

/// User accepted: hide toast, focus main, emit start so main navigates + captures.
#[tauri::command]
pub fn meeting_toast_start_capture(app: AppHandle, title: Option<String>) -> tauri::Result<()> {
    set_meeting_toast_visible(app.clone(), false)?;
    focus_main_window(&app);
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.emit("meeting-toast-start-capture", title);
    }
    Ok(())
}

/// User declined: hide toast, tell main to dismiss (engine cooldown + store clear).
#[tauri::command]
pub fn meeting_toast_dismiss(app: AppHandle) -> tauri::Result<()> {
    set_meeting_toast_visible(app.clone(), false)?;
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.emit("meeting-toast-dismiss", ());
    }
    Ok(())
}

/// User accepted the stop hint while capturing.
#[tauri::command]
pub fn meeting_toast_stop_capture(app: AppHandle) -> tauri::Result<()> {
    set_meeting_toast_visible(app.clone(), false)?;
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.emit("meeting-toast-stop-capture", ());
    }
    Ok(())
}
