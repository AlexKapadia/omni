//! Win32 clipboard save/set/restore for dictation text injection.
//!
//! Owns the unsafe clipboard surface and nothing else: read the current
//! Unicode text (the "save"), write the dictated text, and restore or clear
//! afterwards. Used exclusively by `dictation_text_injection`.
//!
//! Honest limitations (documented, surfaced by the caller):
//! - Only `CF_UNICODETEXT` content is saved/restored. Non-text clipboard
//!   content (images, files) present before injection is LOST when we set
//!   our text — full multi-format preservation is out of scope for M5.
//! - Clipboard managers may capture the transient dictated text.
//!
//! Privacy invariant: after a successful paste the dictated text never
//! LINGERS on the clipboard — we restore the saved text, or clear.

#![cfg(windows)]

use std::time::Duration;

use windows_sys::Win32::Foundation::{GlobalFree, HGLOBAL};
use windows_sys::Win32::System::DataExchange::{
    CloseClipboard, EmptyClipboard, GetClipboardData, IsClipboardFormatAvailable,
    OpenClipboard, SetClipboardData,
};
use windows_sys::Win32::System::Memory::{GlobalAlloc, GlobalLock, GlobalUnlock, GMEM_MOVEABLE};

/// `CF_UNICODETEXT` (winuser.h). Named locally: the only format we touch.
const CF_UNICODETEXT: u32 = 13;

/// The clipboard is a shared, contended resource: another process may hold
/// it for a few ms. Bounded retries, then an honest failure.
const OPEN_RETRIES: u32 = 10;
const OPEN_RETRY_SLEEP: Duration = Duration::from_millis(15);

/// RAII guard: the clipboard MUST be closed on every path, or every other
/// app on the machine loses copy/paste until we exit.
struct OpenClipboardGuard;

impl OpenClipboardGuard {
    fn acquire() -> Result<Self, String> {
        for attempt in 0..OPEN_RETRIES {
            // SAFETY: plain Win32 call; 0 (no owner window) ties it to this thread.
            if unsafe { OpenClipboard(0) } != 0 {
                return Ok(Self);
            }
            if attempt + 1 < OPEN_RETRIES {
                std::thread::sleep(OPEN_RETRY_SLEEP);
            }
        }
        Err("clipboard is held by another application".to_string())
    }
}

impl Drop for OpenClipboardGuard {
    fn drop(&mut self) {
        // SAFETY: guard exists only after a successful OpenClipboard.
        unsafe { CloseClipboard() };
    }
}

/// Read the current clipboard text; `Ok(None)` when no text is present
/// (empty clipboard or non-text content — see module limitations).
pub fn read_clipboard_text() -> Result<Option<String>, String> {
    let _guard = OpenClipboardGuard::acquire()?;
    // SAFETY: guarded; format query is side-effect free.
    if unsafe { IsClipboardFormatAvailable(CF_UNICODETEXT) } == 0 {
        return Ok(None);
    }
    // SAFETY: guarded; the returned handle is owned by the clipboard — we
    // only lock, copy out, and unlock (never free it).
    let handle = unsafe { GetClipboardData(CF_UNICODETEXT) };
    if handle == 0 {
        return Ok(None);
    }
    let hglobal: HGLOBAL = handle as HGLOBAL;
    // SAFETY: valid HGLOBAL from GetClipboardData; unlock follows below.
    let pointer = unsafe { GlobalLock(hglobal) } as *const u16;
    if pointer.is_null() {
        return Err("could not lock clipboard memory".to_string());
    }
    let mut text_utf16: Vec<u16> = Vec::new();
    let mut offset = 0isize;
    loop {
        // SAFETY: CF_UNICODETEXT is NUL-terminated by contract; we stop at
        // the terminator and never read past it.
        let unit = unsafe { *pointer.offset(offset) };
        if unit == 0 {
            break;
        }
        text_utf16.push(unit);
        offset += 1;
    }
    // SAFETY: pairs the successful GlobalLock above.
    unsafe { GlobalUnlock(hglobal) };
    Ok(Some(String::from_utf16_lossy(&text_utf16)))
}

/// Replace the clipboard content with `text` (as `CF_UNICODETEXT`).
pub fn write_clipboard_text(text: &str) -> Result<(), String> {
    let mut units: Vec<u16> = text.encode_utf16().collect();
    units.push(0); // NUL terminator required by CF_UNICODETEXT
    let byte_len = units.len() * std::mem::size_of::<u16>();
    // SAFETY: allocation checked below; ownership transfers to the
    // clipboard on a successful SetClipboardData (we must NOT free it then).
    let hglobal = unsafe { GlobalAlloc(GMEM_MOVEABLE, byte_len) };
    if hglobal.is_null() {
        return Err("could not allocate clipboard memory".to_string());
    }
    // SAFETY: fresh valid HGLOBAL; unlock pairs below; size matches alloc.
    let pointer = unsafe { GlobalLock(hglobal) } as *mut u16;
    if pointer.is_null() {
        // SAFETY: we still own the allocation — free it on this error path.
        unsafe { GlobalFree(hglobal) };
        return Err("could not lock clipboard memory".to_string());
    }
    // SAFETY: destination sized for exactly `units.len()` u16s.
    unsafe { std::ptr::copy_nonoverlapping(units.as_ptr(), pointer, units.len()) };
    // SAFETY: pairs the GlobalLock above.
    unsafe { GlobalUnlock(hglobal) };
    let _guard = OpenClipboardGuard::acquire().inspect_err(|_| {
        // SAFETY: SetClipboardData never ran — the allocation is still ours.
        unsafe { GlobalFree(hglobal) };
    })?;
    // SAFETY: guarded; EmptyClipboard claims ownership for this thread.
    if unsafe { EmptyClipboard() } == 0 {
        // SAFETY: still our allocation (nothing was handed to the clipboard).
        unsafe { GlobalFree(hglobal) };
        return Err("could not take clipboard ownership".to_string());
    }
    // SAFETY: guarded; on success the SYSTEM owns hglobal (no free by us).
    if unsafe { SetClipboardData(CF_UNICODETEXT, hglobal as isize) } == 0 {
        // SAFETY: rejected handle stays ours — free it.
        unsafe { GlobalFree(hglobal) };
        return Err("could not set clipboard text".to_string());
    }
    Ok(())
}

/// Post-injection restore: put the saved text back, or clear the clipboard
/// entirely (privacy invariant: dictated text must not linger).
pub fn restore_clipboard_text(saved: Option<&str>) -> Result<(), String> {
    match saved {
        Some(text) => write_clipboard_text(text),
        None => {
            let _guard = OpenClipboardGuard::acquire()?;
            // SAFETY: guarded; clearing is the deliberate privacy fallback.
            if unsafe { EmptyClipboard() } == 0 {
                return Err("could not clear the clipboard".to_string());
            }
            Ok(())
        }
    }
}
