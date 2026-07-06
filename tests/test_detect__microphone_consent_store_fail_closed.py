"""Mic consent-store interpretation: in-use vs stopped vs unknown, fail closed.

Pins the LastUsedTimeStop semantics (only an exact 0 means in-use), app-name
derivation for packaged/NonPackaged keys, and that reader failures (access
denied, missing subtree) degrade to "no signal + recorded error" — never a
crash and never a fabricated in-use claim.
"""

from collections.abc import Sequence

import pytest

from engine.detect.detection_signal_types import MicrophoneInUse
from engine.detect.microphone_in_use_detector import (
    ConsentStoreEntry,
    MicrophoneInUseDetector,
    app_name_from_consent_key,
)

_ZOOM_KEY = "C:#Program Files#Zoom#bin#Zoom.exe"
# Realistic FILETIME (100ns ticks since 1601) for a PAST stop -> not in use.
_PAST_STOP_FILETIME = 133_600_000_000_000_000


def detector_for(entries: Sequence[ConsentStoreEntry]) -> MicrophoneInUseDetector:
    return MicrophoneInUseDetector(lambda: entries)


def test_stop_zero_means_in_use_nonpackaged() -> None:
    detector = detector_for(
        [ConsentStoreEntry(key_name=_ZOOM_KEY, is_packaged=False, last_used_time_stop=0)]
    )
    assert detector.poll_once() == (MicrophoneInUse(app_name="Zoom.exe", is_packaged=False),)


def test_stop_zero_means_in_use_packaged_family_prefix() -> None:
    detector = detector_for(
        [
            ConsentStoreEntry(
                key_name="MSTeams_8wekyb3d8bbwe", is_packaged=True, last_used_time_stop=0
            )
        ]
    )
    assert detector.poll_once() == (MicrophoneInUse(app_name="MSTeams", is_packaged=True),)


def test_past_stop_time_is_not_in_use() -> None:
    detector = detector_for(
        [
            ConsentStoreEntry(
                key_name=_ZOOM_KEY, is_packaged=False, last_used_time_stop=_PAST_STOP_FILETIME
            )
        ]
    )
    assert detector.poll_once() == ()


def test_missing_stop_value_is_unknown_never_in_use() -> None:
    """None (missing/unreadable value) must fail closed to NO signal."""
    detector = detector_for(
        [ConsentStoreEntry(key_name=_ZOOM_KEY, is_packaged=False, last_used_time_stop=None)]
    )
    assert detector.poll_once() == ()


def test_mixed_entries_only_in_use_apps_emit_sorted_deterministically() -> None:
    entries = [
        ConsentStoreEntry(key_name="C:#apps#discord#Discord.exe", is_packaged=False,
                          last_used_time_stop=0),
        ConsentStoreEntry(key_name=_ZOOM_KEY, is_packaged=False, last_used_time_stop=0),
        ConsentStoreEntry(key_name="C:#apps#obs#obs64.exe", is_packaged=False,
                          last_used_time_stop=_PAST_STOP_FILETIME),
        ConsentStoreEntry(key_name="MSTeams_8wekyb3d8bbwe", is_packaged=True,
                          last_used_time_stop=None),
    ]
    detector = detector_for(entries)
    first = detector.poll_once()
    assert first == detector_for(list(reversed(entries))).poll_once()  # order-independent
    assert [s.app_name for s in first] == ["Discord.exe", "Zoom.exe"]


@pytest.mark.parametrize("error", [PermissionError("access denied"), OSError("key not found")])
def test_reader_failure_degrades_to_no_signal_and_records_error(error: Exception) -> None:
    calls = {"n": 0}

    def flaky_reader() -> Sequence[ConsentStoreEntry]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise error
        return [ConsentStoreEntry(key_name=_ZOOM_KEY, is_packaged=False, last_used_time_stop=0)]

    detector = MicrophoneInUseDetector(flaky_reader)
    assert detector.poll_once() == ()  # fail closed: unknown, not in-use
    assert detector.last_error is not None
    assert detector.poll_once() != ()  # recovery works
    assert detector.last_error is None


def test_empty_store_yields_nothing() -> None:
    assert detector_for([]).poll_once() == ()


def test_rejects_nonpositive_poll_interval() -> None:
    with pytest.raises(ValueError):
        MicrophoneInUseDetector(lambda: [], poll_interval_s=-1.0)


# --- app-name derivation edge cases ------------------------------------------


@pytest.mark.parametrize(
    ("key_name", "is_packaged", "expected"),
    [
        (_ZOOM_KEY, False, "Zoom.exe"),
        ("C:#Users#alex#AppData#Local#Discord#app-1.0#Discord.exe", False, "Discord.exe"),
        ("Zoom.exe", False, "Zoom.exe"),  # no '#' at all: whole name
        ("MSTeams_8wekyb3d8bbwe", True, "MSTeams"),
        ("Microsoft.WindowsCamera_8wekyb3d8bbwe", True, "Microsoft.WindowsCamera"),
        ("NoUnderscorePackage", True, "NoUnderscorePackage"),  # no '_' : whole name
    ],
)
def test_app_name_derivation(key_name: str, is_packaged: bool, expected: str) -> None:
    assert app_name_from_consent_key(key_name, is_packaged) == expected
