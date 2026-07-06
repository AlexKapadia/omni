//! Engine sidecar supervisor.
//!
//! Spawns the Python engine, pipes its stdout/stderr into the app log, and
//! restarts it with exponential backoff (1s, 2s, 4s … capped at 30s) if it
//! exits. The engine may not exist yet (early milestones) — spawn failure is
//! logged and retried, never fatal to the shell. On app exit the whole child
//! process tree is killed so no orphaned engine keeps recording anything
//! (local-only invariant: no capture without a live, visible app).
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

const BACKOFF_START: Duration = Duration::from_secs(1);
const BACKOFF_MAX: Duration = Duration::from_secs(30);
/// A run this long counts as "healthy", so the next crash restarts fast again.
const BACKOFF_RESET_AFTER: Duration = Duration::from_secs(30);
/// Poll granularity for child exit / shutdown checks.
const POLL_INTERVAL: Duration = Duration::from_millis(200);

/// Handle owned by the Tauri app; dropping the app calls `shutdown()`.
pub struct EngineSidecar {
    shutting_down: Arc<AtomicBool>,
    child_slot: Arc<Mutex<Option<Child>>>,
}

impl EngineSidecar {
    /// Start the supervisor thread and return the control handle.
    pub fn spawn_supervised() -> Self {
        let shutting_down = Arc::new(AtomicBool::new(false));
        let child_slot: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
        {
            let shutting_down = Arc::clone(&shutting_down);
            let child_slot = Arc::clone(&child_slot);
            std::thread::Builder::new()
                .name("engine-sidecar-supervisor".into())
                .spawn(move || run_supervisor(&shutting_down, &child_slot))
                .expect("failed to spawn sidecar supervisor thread");
        }
        Self {
            shutting_down,
            child_slot,
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
///
/// Dev builds run the checked-out Python source via uv; release builds will
/// run the PyInstaller binary shipped next to the shell executable (M7 —
/// packaging swaps only this function's release arm).
fn resolve_engine_command() -> Command {
    if cfg!(debug_assertions) {
        // Repo root is three levels above src-tauri (apps/ui/src-tauri).
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
        // Packaged engine (PyInstaller onedir) ships as a bundle resource at
        // <install dir>/omni-engine/omni-engine.exe, next to the shell exe
        // (see tauri.conf.json bundle.resources). If resolution fails we
        // still return a spawnable-looking command; the retry loop reports
        // the miss instead of the shell crashing.
        let engine_path = std::env::current_exe()
            .ok()
            .and_then(|exe| {
                exe.parent()
                    .map(|dir| dir.join("omni-engine").join("omni-engine.exe"))
            })
            .unwrap_or_else(|| PathBuf::from("omni-engine.exe"));
        Command::new(engine_path)
    }
}

/// Supervisor loop: spawn → pipe logs → wait for exit → backoff → respawn.
fn run_supervisor(shutting_down: &AtomicBool, child_slot: &Mutex<Option<Child>>) {
    let mut backoff = BACKOFF_START;
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
                pipe_child_output(&mut child);
                if let Ok(mut slot) = child_slot.lock() {
                    *slot = Some(child);
                }
                let started_at = Instant::now();
                let status = wait_for_exit(shutting_down, child_slot);
                if shutting_down.load(Ordering::SeqCst) {
                    break;
                }
                match status {
                    Some(status) => log::warn!(
                        target: "engine",
                        "engine exited ({status}) after {:.0}s — restarting in {:?}",
                        started_at.elapsed().as_secs_f64(),
                        backoff
                    ),
                    None => log::warn!(target: "engine", "engine wait failed — restarting in {backoff:?}"),
                }
                if started_at.elapsed() >= BACKOFF_RESET_AFTER {
                    backoff = BACKOFF_START; // it ran healthily; crash was fresh
                }
            }
            Err(error) => {
                // Engine absent / uv missing: expected in early milestones.
                log::warn!(
                    target: "engine",
                    "cannot start engine sidecar ({error}) — retrying in {backoff:?}"
                );
            }
        }

        sleep_interruptible(shutting_down, backoff);
        backoff = (backoff * 2).min(BACKOFF_MAX);
    }
    log::info!(target: "engine", "engine sidecar supervisor stopped");
}

/// Forward the child's stdout/stderr line-by-line into the app log so engine
/// tracebacks are visible in one place.
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
                // Python logs to stderr by default — warn keeps it visible
                // without implying every line is an error.
                log::warn!(target: "engine", "{line}");
            }
        });
    }
}

/// Block until the child exits or shutdown is requested. Returns the exit
/// status when the child ended on its own.
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
                Some(Ok(None)) => {} // still running
                Some(Err(_)) | None => {
                    *slot = None;
                    return None;
                }
            }
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

/// Kill the child AND its descendants. `uv run` wraps the real python
/// process, so a plain kill() would orphan the engine — on Windows we use
/// taskkill /T to take down the whole tree.
fn kill_process_tree(mut child: Child) {
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    let _ = child.kill(); // no-op if taskkill already got it; authoritative elsewhere
    let _ = child.wait(); // reap — never leave a zombie
}

/// Sleep for `duration` but wake early if shutdown is requested.
fn sleep_interruptible(shutting_down: &AtomicBool, duration: Duration) {
    let deadline = Instant::now() + duration;
    while Instant::now() < deadline {
        if shutting_down.load(Ordering::SeqCst) {
            return;
        }
        std::thread::sleep(POLL_INTERVAL.min(deadline.saturating_duration_since(Instant::now())));
    }
}
