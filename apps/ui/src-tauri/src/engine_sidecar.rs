//! Engine sidecar supervisor.
//!
//! Spawns the Python engine, pipes its stdout/stderr into the app log, and
//! restarts it with exponential backoff (1s, 2s, 4s … capped at 30s) if it
//! exits. The engine may not exist yet (early milestones) — spawn failure is
//! logged and retried, never fatal to the shell. On app exit the whole child
//! process tree is killed so no orphaned engine keeps recording anything
//! (local-only invariant: no capture without a live, visible app).
//!
//! On Windows the child is placed in a Job Object with
//! `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` so a force-killed shell also kills the
//! engine (no orphaned port 8765 / mic capture).
//!
//! Exactly ONE function decides what to launch (`resolve_engine_command`), so
//! swapping the dev interpreter for the PyInstaller binary at packaging time
//! is a one-place change.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter};

#[cfg(windows)]
use crate::engine_sidecar_job_object_win32::{
    assign_child_to_job, create_kill_on_close_job, WindowsJob,
};

const BACKOFF_START: Duration = Duration::from_secs(1);
const BACKOFF_MAX: Duration = Duration::from_secs(30);
const BACKOFF_RESET_AFTER: Duration = Duration::from_secs(30); // healthy run resets backoff
const POLL_INTERVAL: Duration = Duration::from_millis(200);
const FAST_EXIT_THRESHOLD: Duration = Duration::from_secs(3); // bind/crash-loop detection
const FAST_EXIT_STREAK_FOR_UNHEALTHY: u32 = 3; // emit engine:unhealthy after N

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct EngineUnhealthyPayload {
    reason: String,
    consecutive_fast_exits: u32,
}

/// Handle owned by the Tauri app; dropping the app calls `shutdown()`.
pub struct EngineSidecar {
    shutting_down: Arc<AtomicBool>,
    child_slot: Arc<Mutex<Option<Child>>>,
    /// Windows Job Object handle — held open for the shell lifetime so
    /// force-kill of the shell closes the job and kills the engine tree.
    #[cfg(windows)]
    _job: Option<WindowsJob>,
}

impl EngineSidecar {
    /// Start the supervisor thread and return the control handle.
    pub fn spawn_supervised(app: AppHandle) -> Self {
        let shutting_down = Arc::new(AtomicBool::new(false));
        let child_slot: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));

        #[cfg(windows)]
        let job = create_kill_on_close_job();
        #[cfg(windows)]
        let job_handle = job.as_ref().map(|j| j.handle());

        {
            let shutting_down = Arc::clone(&shutting_down);
            let child_slot = Arc::clone(&child_slot);
            // Non-fatal: thread spawn failure → app still launches (offline-usable).
            if let Err(error) = std::thread::Builder::new()
                .name("engine-sidecar-supervisor".into())
                .spawn(move || {
                    run_supervisor(
                        &shutting_down,
                        &child_slot,
                        app,
                        #[cfg(windows)]
                        job_handle,
                    )
                })
            {
                log::warn!(
                    target: "engine",
                    "could not start engine sidecar supervisor ({error}) — engine features disabled this session"
                );
            }
        }
        Self {
            shutting_down,
            child_slot,
            #[cfg(windows)]
            _job: job,
        }
    }

    /// Stop supervising and kill the engine process tree. Idempotent.
    pub fn shutdown(&self) {
        self.shutting_down.store(true, Ordering::SeqCst);
        if let Ok(mut slot) = self.child_slot.lock() {
            if let Some(child) = slot.take() {
                kill_process_tree(child);
            }
        }
    }
}

/// THE one place that decides how the engine is launched.
fn resolve_engine_command() -> Command {
    if cfg!(debug_assertions) {
        let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../..")
            .canonicalize()
            .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../.."));
        let mut command = Command::new("uv");
        command
            .args(["run", "python", "-m", "engine.server"])
            .current_dir(repo_root);
        command
    } else {
        let bin = if cfg!(windows) {
            "omni-engine.exe"
        } else {
            "omni-engine"
        };
        let path = std::env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(|d| d.join("omni-engine").join(bin)))
            .unwrap_or_else(|| PathBuf::from(bin));
        Command::new(path)
    }
}

fn emit_unhealthy(app: &AppHandle, reason: String, consecutive_fast_exits: u32) {
    let _ = app.emit("engine:unhealthy", EngineUnhealthyPayload { reason, consecutive_fast_exits });
}

/// Supervisor loop: spawn → pipe logs → wait for exit → backoff → respawn.
fn run_supervisor(
    shutting_down: &AtomicBool,
    child_slot: &Mutex<Option<Child>>,
    app: AppHandle,
    #[cfg(windows)] job_handle: Option<isize>,
) {
    let mut backoff = BACKOFF_START;
    let mut consecutive_fast_exits: u32 = 0;
    while !shutting_down.load(Ordering::SeqCst) {
        let mut command = resolve_engine_command();
        command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .stdin(Stdio::null());
        #[cfg(windows)]
        {
            // CREATE_NO_WINDOW: never flash a console at the user.
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000);
        }

        match command.spawn() {
            Ok(mut child) => {
                let pid = child.id();
                log::info!(target: "engine", "engine sidecar started (pid {pid})");
                #[cfg(windows)]
                if let Some(job) = job_handle {
                    assign_child_to_job(job, &child);
                }
                pipe_child_output(&mut child);
                if let Ok(mut slot) = child_slot.lock() {
                    *slot = Some(child);
                }
                let started_at = Instant::now();
                let status = wait_for_exit(shutting_down, child_slot);
                if shutting_down.load(Ordering::SeqCst) {
                    break;
                }
                let lived = started_at.elapsed();
                match status {
                    Some(status) => log::warn!(
                        target: "engine",
                        "engine exited ({status}) after {:.0}s — restarting in {:?}",
                        lived.as_secs_f64(),
                        backoff
                    ),
                    None => log::warn!(
                        target: "engine",
                        "engine wait failed — restarting in {backoff:?}"
                    ),
                }
                if lived < FAST_EXIT_THRESHOLD {
                    consecutive_fast_exits = consecutive_fast_exits.saturating_add(1);
                    if consecutive_fast_exits >= FAST_EXIT_STREAK_FOR_UNHEALTHY {
                        emit_unhealthy(
                            &app,
                            "The local engine keeps exiting immediately. \
                             Another process may be using port 8765, or the \
                             engine failed to start."
                                .to_string(),
                            consecutive_fast_exits,
                        );
                    }
                } else {
                    consecutive_fast_exits = 0;
                }
                if lived >= BACKOFF_RESET_AFTER {
                    backoff = BACKOFF_START;
                }
            }
            Err(error) => {
                log::warn!(
                    target: "engine",
                    "cannot start engine sidecar ({error}) — retrying in {backoff:?}"
                );
                consecutive_fast_exits = consecutive_fast_exits.saturating_add(1);
                if consecutive_fast_exits >= FAST_EXIT_STREAK_FOR_UNHEALTHY {
                    emit_unhealthy(
                        &app,
                        format!("The local engine could not be started ({error})."),
                        consecutive_fast_exits,
                    );
                }
            }
        }

        sleep_interruptible(shutting_down, backoff);
        backoff = (backoff * 2).min(BACKOFF_MAX);
    }
    log::info!(target: "engine", "engine sidecar supervisor stopped");
}

fn pipe_child_output(child: &mut Child) {
    if let Some(stdout) = child.stdout.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                log::info!(target: "engine", "{line}");
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                log::warn!(target: "engine", "{line}");
            }
        });
    }
}

fn wait_for_exit(
    shutting_down: &AtomicBool,
    child_slot: &Mutex<Option<Child>>,
) -> Option<std::process::ExitStatus> {
    loop {
        if shutting_down.load(Ordering::SeqCst) {
            if let Ok(mut slot) = child_slot.lock() {
                if let Some(child) = slot.take() {
                    kill_process_tree(child);
                }
            }
            return None;
        }
        if let Ok(mut slot) = child_slot.lock() {
            match slot.as_mut().map(Child::try_wait) {
                Some(Ok(Some(status))) => {
                    *slot = None;
                    return Some(status);
                }
                Some(Ok(None)) => {}
                Some(Err(_)) | None => {
                    *slot = None;
                    return None;
                }
            }
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

fn kill_process_tree(mut child: Child) {
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn sleep_interruptible(shutting_down: &AtomicBool, duration: Duration) {
    let deadline = Instant::now() + duration;
    while Instant::now() < deadline {
        if shutting_down.load(Ordering::SeqCst) {
            return;
        }
        std::thread::sleep(POLL_INTERVAL.min(deadline.saturating_duration_since(Instant::now())));
    }
}
