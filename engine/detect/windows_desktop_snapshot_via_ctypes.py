"""Real Windows desktop snapshot: processes + visible window titles, ctypes only.

Purpose: the production ``snapshot_provider`` for ``MeetingProcessWatcher``.
Uses ONLY stdlib ctypes against Win32 — no psutil, no subprocess, no
``tasklist`` — so the engine gains no new runtime dependency:

- Process list: ``CreateToolhelp32Snapshot`` + ``Process32FirstW/NextW``
  (kernel32) -> (pid, exe base name) pairs.
- Window titles: ``EnumWindows`` + ``IsWindowVisible`` +
  ``GetWindowTextW`` + ``GetWindowThreadProcessId`` (user32) -> visible
  top-level windows with a non-empty title, attributed to their owning pid.

Pipeline position: composition root (``detection_service`` wiring) injects
``read_desktop_snapshot_via_ctypes`` into ``MeetingProcessWatcher``. Unit
tests inject fakes and never import the win32 branch's internals.

Caveats (honest limits of the mechanism):
- Only TOP-LEVEL window titles are visible; a browser exposes one title per
  window (the ACTIVE tab), so a meeting tab in a background tab is not seen
  until it is foregrounded within its window.
- UWP apps can leave cloaked ghost windows enumerable; the watcher's
  patterns are specific enough that ghosts do not classify as meetings.

Security/compliance invariants:
- Read-only observation of the local session; nothing is written, joined,
  hooked, or sent anywhere.
- Failures raise OSError; the watcher above fails closed to "no signals".
"""

import sys

from engine.detect.detection_signal_types import DesktopSnapshot, ProcessInfo, WindowInfo

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _TH32CS_SNAPPROCESS = 0x00000002
    _MAX_PATH = 260

    class _PROCESSENTRY32W(ctypes.Structure):
        """Win32 PROCESSENTRY32W (Unicode) — field layout per the SDK headers."""

        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),  # ULONG_PTR
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * _MAX_PATH),
        )

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    def _list_processes() -> tuple[ProcessInfo, ...]:
        """Toolhelp32 walk of the process list. Raises OSError on API failure."""
        snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snapshot is None or snapshot == _INVALID_HANDLE_VALUE:
            raise OSError(f"CreateToolhelp32Snapshot failed (winerror {ctypes.get_last_error()})")
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            processes: list[ProcessInfo] = []
            ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                processes.append(
                    ProcessInfo(pid=int(entry.th32ProcessID), exe_name=entry.szExeFile)
                )
                ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return tuple(processes)
        finally:
            _kernel32.CloseHandle(snapshot)  # never leak the snapshot handle

    def _list_visible_window_titles() -> tuple[WindowInfo, ...]:
        """EnumWindows walk: visible, non-empty-titled top-level windows."""
        windows: list[WindowInfo] = []

        def _on_window(hwnd: int, _lparam: int) -> bool:
            if not _user32.IsWindowVisible(hwnd):
                return True  # keep enumerating
            length = _user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buffer, length + 1)
            if not buffer.value:
                return True
            pid = wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append(WindowInfo(pid=int(pid.value), title=buffer.value))
            return True

        # EnumWindows returning FALSE without the callback aborting means the
        # walk itself failed — surface it so the watcher degrades honestly.
        if not _user32.EnumWindows(_WNDENUMPROC(_on_window), 0):
            raise OSError(f"EnumWindows failed (winerror {ctypes.get_last_error()})")
        return tuple(windows)

    def read_desktop_snapshot_via_ctypes() -> DesktopSnapshot:
        """Production snapshot provider (see module docstring)."""
        return DesktopSnapshot(processes=_list_processes(), windows=_list_visible_window_titles())

else:  # pragma: no cover — non-Windows: no Win32 desktop to observe

    def read_desktop_snapshot_via_ctypes() -> DesktopSnapshot:
        """Non-Windows stub: fail closed (watcher degrades to no signals)."""
        raise OSError("desktop snapshot requires Win32 (EnumWindows/Toolhelp32)")
