"""has_kept_audio: true only when me/them mp3|wav exists under keep_audio dir."""

from pathlib import Path

from engine.enhance.meeting_kept_audio import meeting_has_kept_audio
from engine.enhance.meeting_summary_presenter import meeting_detail_payload
from engine.storage.meetings_repository import MeetingRow

START = "2026-07-06T10:00:00+00:00"


def test_has_kept_audio_false_when_session_dir_missing(tmp_path: Path) -> None:
    assert meeting_has_kept_audio("m-missing", audio_root=tmp_path) is False


def test_has_kept_audio_true_for_them_mp3(tmp_path: Path) -> None:
    session = tmp_path / "m-1"
    session.mkdir()
    (session / "them.mp3").write_bytes(b"x")
    assert meeting_has_kept_audio("m-1", audio_root=tmp_path) is True


def test_has_kept_audio_true_for_me_wav(tmp_path: Path) -> None:
    session = tmp_path / "m-2"
    session.mkdir()
    (session / "me.wav").write_bytes(b"RIFF")
    assert meeting_has_kept_audio("m-2", audio_root=tmp_path) is True


def test_has_kept_audio_false_when_only_unrelated_files(tmp_path: Path) -> None:
    session = tmp_path / "m-3"
    session.mkdir()
    (session / "notes.txt").write_text("x", encoding="utf-8")
    assert meeting_has_kept_audio("m-3", audio_root=tmp_path) is False


def test_detail_payload_includes_has_kept_audio_flag() -> None:
    row = MeetingRow(
        id="m-1",
        title="Vendor sync",
        started_at=START,
        ended_at="2026-07-06T10:01:30+00:00",
        note_path=None,
        notes_text="",
        enhanced_notes_md="",
        finalized_at=None,
    )
    payload = meeting_detail_payload(row, [], has_kept_audio=True)
    assert payload["has_kept_audio"] is True
    payload_off = meeting_detail_payload(row, [], has_kept_audio=False)
    assert payload_off["has_kept_audio"] is False
