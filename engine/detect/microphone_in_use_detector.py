"""Microphone-in-use detection via the Windows capability consent store.

Purpose: tell the rules engine WHICH apps currently hold the microphone, as
corroboration for weak meeting-app signals (Discord/Zoom idling in the tray
vs actually in a call).

Mechanism (documented contract): Windows 10 1903+ tracks per-app microphone
usage under::

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\
        CapabilityAccessManager\\ConsentStore\\microphone

- Packaged (Store/UWP) apps are direct subkeys named by package family
  (e.g. ``MSTeams_8wekyb3d8bbwe``).
- Classic desktop apps live under the ``NonPackaged`` subkey, named by exe
  path with ``\\`` replaced by ``#`` (e.g. ``C:#...#Zoom#bin#Zoom.exe``).
- Each key carries ``LastUsedTimeStart`` / ``LastUsedTimeStop`` (REG_QWORD
  FILETIME). ``LastUsedTimeStop == 0`` with a non-zero start means the app
  is using the microphone RIGHT NOW.

Caveats (why this signal is corroboration-only, never auto-start alone):
- HKCU covers the CURRENT user session only.
- An app that crashed while holding the mic can leave a stale ``Stop == 0``
  (false positive) until it next runs.
- Audio paths that bypass the capability manager (some legacy drivers /
  kernel streaming) never appear here (false negative).
- The subtree layout is an OS implementation detail; missing keys or values
  must degrade to "unknown", never crash.

Pipeline position: injected reader -> ``MicrophoneInUseDetector.poll_once``
-> ``AutoStartRulesEngine`` (corroboration boost only).

Security/compliance invariants:
- Read-only registry access under HKCU; nothing is written, nothing leaves
  the machine.
- Fail closed to "unknown": reader errors (access denied, missing subtree)
  yield NO signals plus a recorded ``last_error`` — never a crash, never a
  fabricated in-use claim.
"""

import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from engine.detect.detection_signal_types import MicrophoneInUse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConsentStoreEntry:
    """One raw consent-store key, before interpretation.

    ``last_used_time_stop`` is ``None`` when the value is missing or
    unreadable — interpreted as UNKNOWN (no signal), never as in-use.
    """

    key_name: str
    is_packaged: bool
    last_used_time_stop: int | None


ConsentStoreReader = Callable[[], Sequence[ConsentStoreEntry]]


def app_name_from_consent_key(key_name: str, is_packaged: bool) -> str:
    """Derive a human-meaningful app name from a consent-store key name.

    NonPackaged keys encode the exe path with ``#`` separators -> take the
    final component (the exe base name). Packaged keys are package family
    names -> take the name before the publisher-hash suffix.
    """
    if is_packaged:
        return key_name.split("_", 1)[0]
    return key_name.rsplit("#", 1)[-1]


class MicrophoneInUseDetector:
    """Interprets injected consent-store entries into MicrophoneInUse signals."""

    def __init__(self, reader: ConsentStoreReader, poll_interval_s: float = 3.0) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        self._reader = reader
        self.poll_interval_s = poll_interval_s
        self.last_error: str | None = None

    def poll_once(self) -> tuple[MicrophoneInUse, ...]:
        """One poll. Stop==0 -> in use; missing value -> unknown -> no signal."""
        try:
            entries = self._reader()
        except Exception as exc:  # fail closed: unknown, never crash
            first_failure = self.last_error is None
            self.last_error = f"{type(exc).__name__}: {exc}"
            log = logger.warning if first_failure else logger.debug
            log("mic consent store unreadable; mic signal degraded: %s", self.last_error)
            return ()
        self.last_error = None
        signals: list[MicrophoneInUse] = []
        for entry in entries:
            # WHY strict == 0: None (missing/unreadable) means UNKNOWN and a
            # positive FILETIME means "stopped at that time" — only an exact
            # zero documents an in-progress use. Fail closed on everything else.
            if entry.last_used_time_stop == 0:
                signals.append(
                    MicrophoneInUse(
                        app_name=app_name_from_consent_key(entry.key_name, entry.is_packaged),
                        is_packaged=entry.is_packaged,
                    )
                )
        # Deterministic output order for identical registry states.
        return tuple(sorted(signals, key=lambda s: (s.app_name, s.is_packaged)))


_CONSENT_STORE_MICROPHONE_PATH = (
    r"Software\Microsoft\Windows\CurrentVersion"
    r"\CapabilityAccessManager\ConsentStore\microphone"
)

if sys.platform == "win32":
    import winreg

    def _read_stop_value(mic_key: "winreg.HKEYType", subkey_name: str) -> int | None:
        """Read LastUsedTimeStop for one app key; None if missing/unreadable."""
        try:
            with winreg.OpenKey(mic_key, subkey_name) as app_key:
                value, value_type = winreg.QueryValueEx(app_key, "LastUsedTimeStop")
        except OSError:
            return None  # fail closed: unknown, not in-use
        # REG_QWORD comes back as int; anything else is unexpected -> unknown.
        if value_type != winreg.REG_QWORD or not isinstance(value, int):
            return None
        return value

    def _subkey_names(key: "winreg.HKEYType") -> list[str]:
        names: list[str] = []
        index = 0
        while True:
            try:
                names.append(winreg.EnumKey(key, index))
            except OSError:
                return names  # ERROR_NO_MORE_ITEMS ends enumeration
            index += 1

    def read_microphone_consent_store_via_winreg() -> list[ConsentStoreEntry]:
        """Production reader: walk HKCU packaged + NonPackaged mic subkeys.

        Raises OSError if the consent-store subtree itself is unreadable —
        the detector above catches it and degrades to "unknown".
        """
        entries: list[ConsentStoreEntry] = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CONSENT_STORE_MICROPHONE_PATH) as mic_key:
            for name in _subkey_names(mic_key):
                if name == "NonPackaged":
                    with winreg.OpenKey(mic_key, name) as nonpackaged_key:
                        for exe_key_name in _subkey_names(nonpackaged_key):
                            entries.append(
                                ConsentStoreEntry(
                                    key_name=exe_key_name,
                                    is_packaged=False,
                                    last_used_time_stop=_read_stop_value(
                                        nonpackaged_key, exe_key_name
                                    ),
                                )
                            )
                else:
                    entries.append(
                        ConsentStoreEntry(
                            key_name=name,
                            is_packaged=True,
                            last_used_time_stop=_read_stop_value(mic_key, name),
                        )
                    )
        return entries

else:  # pragma: no cover — non-Windows: mic consent store does not exist

    def read_microphone_consent_store_via_winreg() -> list[ConsentStoreEntry]:
        """Non-Windows stub: fail closed (detector degrades to no signal)."""
        raise OSError("microphone consent store is Windows-only (HKCU CapabilityAccessManager)")
