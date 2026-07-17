"""Media import must index the new meeting transcript (fail-soft)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engine.import_.media_import_service import import_media_file
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.stt.stt_backend_protocol import SttSegment
from engine.vault.vault_paths import VAULT_DIR_ENV_VAR


class _FakeBackend:
    def transcribe_samples(
        self,
        samples: object,
        *,
        stream: str,
        on_partial: object = None,
    ) -> list[SttSegment]:
        return [SttSegment(text="Imported hello", t_start=0.0, t_end=1.0, stream="them")]

    def transcribe_file(self, path: str) -> list[SttSegment]:
        raise AssertionError("not used")


@pytest.mark.asyncio
async def test_import_media_file_indexes_transcript(
    tmp_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "clip.wav"
    media.write_bytes(b"RIFF")
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv(VAULT_DIR_ENV_VAR, str(vault))
    monkeypatch.setattr(
        "engine.import_.media_import_service.shutil.which",
        lambda _name: "/usr/bin/ffmpeg",
    )
    monkeypatch.setattr(
        "engine.import_.media_import_service.decode_media_to_mono_16k",
        lambda _path: np.zeros(16_000, dtype=np.float32),
    )

    async def _load_backend(
        _connection: object, *, models_dir: Path | None = None
    ) -> _FakeBackend:
        return _FakeBackend()

    monkeypatch.setattr(
        "engine.import_.media_import_service.load_stt_backend_from_settings",
        _load_backend,
    )

    db_path = tmp_path / "omni.db"
    meeting_id = await import_media_file(
        db_path, real_migrations_dir, str(media), "Import Test"
    )

    connection = await open_sqlite_connection(db_path)
    try:
        cursor = await connection.execute(
            "SELECT text FROM chunks WHERE note_path = ?",
            (f"transcript://{meeting_id}",),
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        assert "Imported hello" in str(row[0])
    finally:
        await connection.close()
