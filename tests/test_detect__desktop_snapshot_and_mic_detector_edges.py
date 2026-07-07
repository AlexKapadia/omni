"""Adversarial tests for the Windows-only ctypes/winreg readers.

Both readers live behind ``if sys.platform == "win32"`` and bind real OS
handles at import time, so they are exercised by monkeypatching the bound
module globals (``_kernel32`` / ``_user32`` / ``winreg``) with FAKES that
emulate the Win32/registry call contract. No real EnumWindows, Toolhelp32,
or HKCU access happens. Every assertion pins EXACT parsed output and each
fail-closed branch (invisible/untitled windows, missing/typed values,
enumeration termination) so a regression in the parsing or filtering logic
would FAIL the test.

The desktop-snapshot ``_WNDENUMPROC`` (a ctypes callback factory) is
replaced with an identity wrapper so the enumeration callback is driven as
a plain Python function — sidestepping ctypes-callback invocation while
still exercising every line of ``_on_window``.
"""

import sys
from typing import Any, cast

import pytest

from engine.detect import microphone_in_use_detector as mic_mod
from engine.detect import windows_desktop_snapshot_via_ctypes as snap_mod
from engine.detect.detection_signal_types import (
    DesktopSnapshot,
    MicrophoneInUse,
    ProcessInfo,
    WindowInfo,
)
from engine.detect.microphone_in_use_detector import (
    ConsentStoreEntry,
    MicrophoneInUseDetector,
)

win32_only = pytest.mark.skipif(
    sys.platform != "win32", reason="ctypes/winreg readers exist only on win32"
)

# Realistic FILETIME (100ns ticks since 1601) for a PAST stop -> not in use.
_PAST_STOP = 133_600_000_000_000_000


# ==========================================================================
# windows_desktop_snapshot_via_ctypes: process + window enumeration.
# ==========================================================================


class _FakeKernel32:
    """Emulates the Toolhelp32 process walk over a scripted process list."""

    def __init__(self, procs: list[tuple[int, str]], *, snapshot: Any = 4321) -> None:
        self._procs = procs
        self._snapshot = snapshot
        self._i = 0
        self.closed_with: Any = "unset"

    def CreateToolhelp32Snapshot(self, flags: int, th32_process_id: int) -> Any:
        return self._snapshot

    def Process32FirstW(self, snapshot: Any, entry_ref: Any) -> int:
        self._i = 0
        return self._fill(entry_ref)

    def Process32NextW(self, snapshot: Any, entry_ref: Any) -> int:
        return self._fill(entry_ref)

    def _fill(self, entry_ref: Any) -> int:
        if self._i >= len(self._procs):
            return 0  # ERROR_NO_MORE_FILES -> ends the walk
        pid, exe = self._procs[self._i]
        self._i += 1
        entry = entry_ref._obj
        entry.th32ProcessID = pid
        entry.szExeFile = exe
        return 1

    def CloseHandle(self, snapshot: Any) -> int:
        self.closed_with = snapshot
        return 1


class _FakeUser32:
    """Emulates EnumWindows + the per-window text/pid getters."""

    def __init__(self, windows: list[dict[str, Any]], *, enum_ok: bool = True) -> None:
        self._by_hwnd = {w["hwnd"]: w for w in windows}
        self._order = [w["hwnd"] for w in windows]
        self._enum_ok = enum_ok

    def EnumWindows(self, proc: Any, lparam: int) -> int:
        for hwnd in self._order:
            proc(hwnd, lparam)
        return 1 if self._enum_ok else 0

    def IsWindowVisible(self, hwnd: int) -> int:
        return 1 if self._by_hwnd[hwnd]["visible"] else 0

    def GetWindowTextLengthW(self, hwnd: int) -> int:
        return int(self._by_hwnd[hwnd]["length"])

    def GetWindowTextW(self, hwnd: int, buffer: Any, maxcount: int) -> int:
        buffer.value = self._by_hwnd[hwnd]["text"]
        return len(buffer.value)

    def GetWindowThreadProcessId(self, hwnd: int, pid_ref: Any) -> int:
        pid_ref._obj.value = self._by_hwnd[hwnd]["pid"]
        return 1


def _patch_kernel(monkeypatch: pytest.MonkeyPatch, fake: _FakeKernel32) -> None:
    monkeypatch.setattr(snap_mod, "_kernel32", fake)


def _patch_user(monkeypatch: pytest.MonkeyPatch, fake: _FakeUser32) -> None:
    monkeypatch.setattr(snap_mod, "_user32", fake)
    # Drive the enum callback as a plain function (no ctypes callback bind).
    monkeypatch.setattr(snap_mod, "_WNDENUMPROC", lambda func: func)


@win32_only
def test_list_processes_parses_pid_and_exe_and_closes_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeKernel32([(100, "Zoom.exe"), (4, "System"), (200, "Teams.exe")])
    _patch_kernel(monkeypatch, fake)
    result = snap_mod._list_processes()
    assert result == (
        ProcessInfo(pid=100, exe_name="Zoom.exe"),
        ProcessInfo(pid=4, exe_name="System"),
        ProcessInfo(pid=200, exe_name="Teams.exe"),
    )
    assert fake.closed_with == 4321  # snapshot handle never leaked


@win32_only
def test_list_processes_empty_walk_still_closes_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeKernel32([])
    _patch_kernel(monkeypatch, fake)
    assert snap_mod._list_processes() == ()
    assert fake.closed_with == 4321


@win32_only
def test_list_processes_raises_on_invalid_snapshot_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_kernel(monkeypatch, _FakeKernel32([(1, "x.exe")], snapshot=None))
    with pytest.raises(OSError, match="CreateToolhelp32Snapshot failed"):
        snap_mod._list_processes()


@win32_only
def test_list_processes_raises_on_invalid_handle_value_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_kernel(
        monkeypatch, _FakeKernel32([(1, "x.exe")], snapshot=snap_mod._INVALID_HANDLE_VALUE)
    )
    with pytest.raises(OSError, match="CreateToolhelp32Snapshot failed"):
        snap_mod._list_processes()


@win32_only
def test_list_visible_windows_filters_and_attributes_to_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = [
        {"hwnd": 1, "visible": True, "length": 12, "text": "Zoom Meeting", "pid": 100},
        {"hwnd": 2, "visible": False, "length": 9, "text": "Hidden", "pid": 101},  # not visible
        {"hwnd": 3, "visible": True, "length": 0, "text": "", "pid": 102},  # zero length
        {"hwnd": 4, "visible": True, "length": 8, "text": "", "pid": 103},  # empty despite length
        {"hwnd": 5, "visible": True, "length": 15, "text": "General - Slack", "pid": 200},
    ]
    _patch_user(monkeypatch, _FakeUser32(windows))
    result = snap_mod._list_visible_window_titles()
    assert result == (
        WindowInfo(pid=100, title="Zoom Meeting"),
        WindowInfo(pid=200, title="General - Slack"),
    )


@win32_only
def test_list_visible_windows_raises_when_enumwindows_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_user(monkeypatch, _FakeUser32([], enum_ok=False))
    with pytest.raises(OSError, match="EnumWindows failed"):
        snap_mod._list_visible_window_titles()


@win32_only
def test_read_desktop_snapshot_composes_processes_and_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_kernel(monkeypatch, _FakeKernel32([(100, "Zoom.exe")]))
    _patch_user(
        monkeypatch,
        _FakeUser32([{"hwnd": 1, "visible": True, "length": 12, "text": "Zoom Meeting",
                      "pid": 100}]),
    )
    result = snap_mod.read_desktop_snapshot_via_ctypes()
    assert result == DesktopSnapshot(
        processes=(ProcessInfo(pid=100, exe_name="Zoom.exe"),),
        windows=(WindowInfo(pid=100, title="Zoom Meeting"),),
    )


# ==========================================================================
# microphone_in_use_detector: winreg reader (production path).
# ==========================================================================

_REG_QWORD = 11
_REG_DWORD = 4


class _FakeRegKey:
    """One fake registry key: named subkeys + named values. A context mgr."""

    def __init__(self, *, subkeys: dict[str, "_FakeRegKey"] | None = None,
                 values: dict[str, tuple[Any, int]] | None = None) -> None:
        self.subkeys = subkeys or {}
        self.values = values or {}
        self.closed = False

    def __enter__(self) -> "_FakeRegKey":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.closed = True


class _FakeWinreg:
    """Emulates the winreg surface the reader uses, over a fake key tree."""

    REG_QWORD = _REG_QWORD
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, root: _FakeRegKey | None, *, root_error: Exception | None = None) -> None:
        self._root = root
        self._root_error = root_error

    def OpenKey(self, key: Any, subkey: str) -> _FakeRegKey:
        if key == self.HKEY_CURRENT_USER:
            if self._root_error is not None:
                raise self._root_error
            assert self._root is not None
            return self._root
        if subkey not in key.subkeys:
            raise OSError(2, "subkey not found")
        child: _FakeRegKey = key.subkeys[subkey]
        return child

    def QueryValueEx(self, key: _FakeRegKey, name: str) -> tuple[Any, int]:
        if name not in key.values:
            raise OSError(2, "value not found")
        return key.values[name]

    def EnumKey(self, key: _FakeRegKey, index: int) -> str:
        names = list(key.subkeys.keys())
        if index >= len(names):
            raise OSError(259, "no more items")
        return names[index]


def _build_tree() -> _FakeRegKey:
    return _FakeRegKey(
        subkeys={
            "MSTeams_8wekyb3d8bbwe": _FakeRegKey(values={"LastUsedTimeStop": (0, _REG_QWORD)}),
            "Foo_hash": _FakeRegKey(values={"LastUsedTimeStop": (_PAST_STOP, _REG_QWORD)}),
            "BadType_hash": _FakeRegKey(values={"LastUsedTimeStop": (0, _REG_DWORD)}),  # wrong type
            "StrVal_hash": _FakeRegKey(values={"LastUsedTimeStop": ("0", _REG_QWORD)}),  # not int
            "NoValue_hash": _FakeRegKey(values={}),  # value missing -> OSError -> None
            "NonPackaged": _FakeRegKey(
                subkeys={
                    "C:#Program Files#Zoom#bin#Zoom.exe": _FakeRegKey(
                        values={"LastUsedTimeStop": (0, _REG_QWORD)}
                    ),
                    "C:#apps#obs#obs64.exe": _FakeRegKey(
                        values={"LastUsedTimeStop": (_PAST_STOP, _REG_QWORD)}
                    ),
                }
            ),
        }
    )


@win32_only
def test_reader_walks_packaged_and_nonpackaged_into_exact_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mic_mod, "winreg", _FakeWinreg(_build_tree()))
    entries = mic_mod.read_microphone_consent_store_via_winreg()
    assert entries == [
        ConsentStoreEntry(key_name="MSTeams_8wekyb3d8bbwe", is_packaged=True,
                          last_used_time_stop=0),
        ConsentStoreEntry(key_name="Foo_hash", is_packaged=True, last_used_time_stop=_PAST_STOP),
        ConsentStoreEntry(key_name="BadType_hash", is_packaged=True, last_used_time_stop=None),
        ConsentStoreEntry(key_name="StrVal_hash", is_packaged=True, last_used_time_stop=None),
        ConsentStoreEntry(key_name="NoValue_hash", is_packaged=True, last_used_time_stop=None),
        ConsentStoreEntry(key_name="C:#Program Files#Zoom#bin#Zoom.exe", is_packaged=False,
                          last_used_time_stop=0),
        ConsentStoreEntry(key_name="C:#apps#obs#obs64.exe", is_packaged=False,
                          last_used_time_stop=_PAST_STOP),
    ]


@win32_only
def test_reader_output_drives_detector_to_exact_in_use_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mic_mod, "winreg", _FakeWinreg(_build_tree()))
    detector = MicrophoneInUseDetector(mic_mod.read_microphone_consent_store_via_winreg)
    # Only the two Stop==0 apps are in use, sorted (app_name, is_packaged).
    assert detector.poll_once() == (
        MicrophoneInUse(app_name="MSTeams", is_packaged=True),
        MicrophoneInUse(app_name="Zoom.exe", is_packaged=False),
    )
    assert detector.last_error is None


@win32_only
def test_reader_propagates_oserror_when_subtree_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mic_mod, "winreg", _FakeWinreg(None, root_error=OSError("access denied"))
    )
    with pytest.raises(OSError, match="access denied"):
        mic_mod.read_microphone_consent_store_via_winreg()


@win32_only
def test_reader_oserror_is_caught_by_detector_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The detector's fail-closed wrapper turns the reader's OSError into
    # "no signal + recorded error", never a crash or a fabricated in-use.
    monkeypatch.setattr(
        mic_mod, "winreg", _FakeWinreg(None, root_error=OSError("consent store gone"))
    )
    detector = MicrophoneInUseDetector(mic_mod.read_microphone_consent_store_via_winreg)
    assert detector.poll_once() == ()
    assert detector.last_error is not None
    assert "consent store gone" in detector.last_error


@win32_only
@pytest.mark.parametrize(
    ("value", "value_type", "expected"),
    [
        (0, _REG_QWORD, 0),  # in-use marker: exact zero survives
        (133_600_000_000_000_000, _REG_QWORD, 133_600_000_000_000_000),  # past stop passes through
        (0, _REG_DWORD, None),  # wrong registry type -> unknown
        ("0", _REG_QWORD, None),  # non-int payload -> unknown
    ],
)
def test_read_stop_value_type_and_value_guards(
    monkeypatch: pytest.MonkeyPatch, value: Any, value_type: int, expected: int | None
) -> None:
    mic_key = _FakeRegKey(subkeys={"App": _FakeRegKey(values={"LastUsedTimeStop": (value,
                                                                                   value_type)})})
    monkeypatch.setattr(mic_mod, "winreg", _FakeWinreg(mic_key))
    assert mic_mod._read_stop_value(cast(Any, mic_key), "App") == expected


@win32_only
def test_read_stop_value_missing_value_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    mic_key = _FakeRegKey(subkeys={"App": _FakeRegKey(values={})})
    monkeypatch.setattr(mic_mod, "winreg", _FakeWinreg(mic_key))
    assert mic_mod._read_stop_value(cast(Any, mic_key), "App") is None


@win32_only
def test_read_stop_value_missing_subkey_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    mic_key = _FakeRegKey(subkeys={})
    monkeypatch.setattr(mic_mod, "winreg", _FakeWinreg(mic_key))
    # OpenKey on an absent app subkey raises OSError -> fail closed to None.
    assert mic_mod._read_stop_value(cast(Any, mic_key), "Nonexistent") is None


@win32_only
def test_subkey_names_enumerates_then_terminates_on_no_more_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mic_mod, "winreg", _FakeWinreg(None))
    key = _FakeRegKey(subkeys={"A": _FakeRegKey(), "B": _FakeRegKey(), "C": _FakeRegKey()})
    assert mic_mod._subkey_names(cast(Any, key)) == ["A", "B", "C"]


@win32_only
def test_subkey_names_empty_key_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mic_mod, "winreg", _FakeWinreg(None))
    assert mic_mod._subkey_names(cast(Any, _FakeRegKey(subkeys={}))) == []
