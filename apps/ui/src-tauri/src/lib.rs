//! Omni desktop shell: builds the Tauri app, wires the tray, and supervises
//! the Python engine sidecar. The shell is deliberately thin — it never
//! touches audio, transcripts, or keys; that is the engine's job.

mod dictation_pill_window;
mod engine_sidecar;
mod tray;

use tauri::{AppHandle, Manager, RunEvent};

/// Bring the main window to the foreground (used by the tray and by a second
/// app launch via the single-instance plugin).
fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        // Best-effort: a hidden/minimised window must still come forward.
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // Single instance MUST be the first plugin so a second launch is
        // intercepted before any other state is created.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            focus_main_window(app);
        }))
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            tray::build_tray(app.handle())?;
            // M5: hold-F9 dictation pill (window + global shortcut binding).
            dictation_pill_window::setup_dictation_pill(app.handle())?;
            // Start supervising the engine sidecar immediately; the supervisor
            // tolerates the engine being absent (retry loop, never a crash).
            let sidecar = engine_sidecar::EngineSidecar::spawn_supervised();
            app.manage(sidecar);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Omni");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            // Contract: never leave an orphaned engine process behind.
            app_handle
                .state::<engine_sidecar::EngineSidecar>()
                .shutdown();
        }
    });
}
