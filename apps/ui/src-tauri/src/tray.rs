//! System tray: icon + menu (Show Omni Steroid / Record a meeting / Quit).
//!
//! The tray is the product's always-available surface: "Record a meeting"
//! emits to the main window to jump straight into capture (human copy that
//! matches the in-app "Record" nav label).

use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager,
};

const MENU_ID_SHOW: &str = "show-omni";
const MENU_ID_START_CAPTURE: &str = "start-capture";
const MENU_ID_QUIT: &str = "quit";

/// Build the tray icon and its menu on the given app handle.
pub fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let show = MenuItemBuilder::with_id(MENU_ID_SHOW, "Show Omni Steroid").build(app)?;
    let start_capture = MenuItemBuilder::with_id(MENU_ID_START_CAPTURE, "Record a meeting")
        .enabled(true)
        .build(app)?;
    let quit = MenuItemBuilder::with_id(MENU_ID_QUIT, "Quit").build(app)?;

    let menu = MenuBuilder::new(app)
        .item(&show)
        .item(&start_capture)
        .separator()
        .item(&quit)
        .build()?;

    let mut tray = TrayIconBuilder::with_id("omni-tray")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .tooltip("Omni Steroid");
    // Reuse the window icon; if it is somehow absent we still build a tray —
    // a menu without an icon beats no tray at all.
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.on_menu_event(|app, event| match event.id().as_ref() {
        MENU_ID_SHOW => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }
        MENU_ID_START_CAPTURE => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.emit("tray-start-capture", ());
            }
        }
        MENU_ID_QUIT => app.exit(0),
        _ => {}
    })
    .build(app)?;

    Ok(())
}
