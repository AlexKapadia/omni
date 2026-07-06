// Binary entry point. All real wiring lives in lib.rs so the same code path
// serves the desktop binary and any future integration harness.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    omni_ui_lib::run()
}
