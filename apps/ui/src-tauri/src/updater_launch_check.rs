//! Auto-update: launch-time check + UI-driven install, via GitHub Releases.
//!
//! The updater plugin reads its endpoint + signature public key from
//! tauri.conf.json (`plugins.updater`): every artifact is verified against
//! the pinned minisign public key before install — a compromised download
//! host cannot ship code (fail closed).
//!
//! Event surface (consumed by Settings / onboarding — stable names):
//! - `updater:checking`            — a check has started
//! - `updater:update-available`    — { version, currentVersion, notes }
//! - `updater:up-to-date`          — no newer release
//! - `updater:error`               — { message } (network down is NOT fatal)
//! - `updater:download-progress`   — { downloadedBytes, totalBytes|null }
//! - `updater:installed`           — install finished; call `updater_restart_app`
//!
//! Command surface:
//! - `updater_download_and_install` — re-checks, downloads + installs
//! - `updater_restart_app`          — relaunches into the new version

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use tauri_plugin_updater::UpdaterExt;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct UpdateAvailablePayload {
    version: String,
    current_version: String,
    notes: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DownloadProgressPayload {
    downloaded_bytes: usize,
    total_bytes: Option<u64>,
}

#[derive(Clone, Serialize)]
struct ErrorPayload {
    message: String,
}

fn emit_error(app: &AppHandle, error: &tauri_plugin_updater::Error) {
    let _ = app.emit(
        "updater:error",
        ErrorPayload {
            message: error.to_string(),
        },
    );
}

/// Check GitHub Releases once and report the result as events. Never blocks
/// startup and never fails the app — offline is an `updater:error` event.
pub fn spawn_launch_check(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let _ = app.emit("updater:checking", ());
        let updater = match app.updater() {
            Ok(updater) => updater,
            Err(error) => {
                emit_error(&app, &error);
                return;
            }
        };
        match updater.check().await {
            Ok(Some(update)) => {
                let _ = app.emit(
                    "updater:update-available",
                    UpdateAvailablePayload {
                        version: update.version.clone(),
                        current_version: update.current_version.clone(),
                        notes: update.body.clone(),
                    },
                );
            }
            Ok(None) => {
                let _ = app.emit("updater:up-to-date", ());
            }
            Err(error) => emit_error(&app, &error),
        }
    });
}

/// Download and install the pending update (signature-verified by the
/// plugin). Stateless: re-checks so the UI needs no handle to the update.
#[tauri::command]
pub async fn updater_download_and_install(app: AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|error| error.to_string())?;
    let update = updater
        .check()
        .await
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "no update available".to_string())?;

    let progress_app = app.clone();
    update
        .download_and_install(
            move |downloaded_bytes, total_bytes| {
                let _ = progress_app.emit(
                    "updater:download-progress",
                    DownloadProgressPayload {
                        downloaded_bytes,
                        total_bytes,
                    },
                );
            },
            || {},
        )
        .await
        .map_err(|error| error.to_string())?;

    let _ = app.emit("updater:installed", ());
    Ok(())
}

/// Relaunch into the freshly-installed version. The RunEvent::Exit handler
/// still fires, so the engine sidecar is shut down cleanly first.
#[tauri::command]
pub fn updater_restart_app(app: AppHandle) {
    app.restart();
}
