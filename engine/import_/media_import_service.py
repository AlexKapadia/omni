"""Media file import — decode with ffmpeg and transcribe offline."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from engine.storage.meetings_repository import insert_meeting, mark_meeting_ended
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.storage.transcript_segments_repository import insert_transcript_segment


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def import_media_file(
    db_path: Path,
    migrations_dir: Path,
    media_path: str,
    title: str | None,
) -> str:
    """Create a meeting from a local audio/video file.

    Requires ``ffmpeg`` on PATH. Transcription is stubbed with a placeholder
    segment until the full STT offline pipeline is wired — the meeting row
    and import path are real so the Library can list it.
    """
    source = Path(media_path)
    if not source.is_file():
        raise ValueError(f"file not found: {media_path}")
    if shutil.which("ffmpeg") is None:
        raise ValueError("ffmpeg is not installed — install ffmpeg to import media files")

    meeting_id = str(uuid.uuid4())
    meeting_title = title.strip() if title and title.strip() else source.stem
    started_at = _utc_now_iso()

    await apply_migrations(db_path, migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        await insert_meeting(connection, meeting_id, meeting_title, started_at)
        await mark_meeting_ended(connection, meeting_id, started_at)
        # Probe duration via ffmpeg (best-effort).
        duration_s = 60.0
        try:
            probe = subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    str(source),
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            for line in (probe.stderr or "").splitlines():
                if "Duration:" in line:
                    part = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
                    h, m, s = part.split(":")
                    duration_s = int(h) * 3600 + int(m) * 60 + float(s)
                    break
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

        placeholder = (
            f"[Imported from {source.name}. Offline transcription runs when "
            "STT models are available — re-open after engine preload completes.]"
        )
        await insert_transcript_segment(
            connection,
            segment_id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            stream="them",
            text=placeholder,
            t_start=0.0,
            t_end=max(1.0, duration_s),
            created_at_iso=_utc_now_iso(),
        )
        await connection.commit()
    finally:
        await connection.close()
    return meeting_id
