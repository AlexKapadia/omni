"""Whisper ggml catalog: Meetily-compatible presence + URL builders."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.stt.whisper_model_catalog import (
    DEFAULT_WHISPER_MODEL_ID,
    WHISPER_MODEL_IDS,
    download_whisper_model,
    is_whisper_model_present,
    whisper_download_url,
    whisper_ggml_filename,
    whisper_model_path,
)


def test_default_model_is_meetily_large_v3_turbo() -> None:
    assert DEFAULT_WHISPER_MODEL_ID == "large-v3-turbo"
    assert "large-v3-turbo" in WHISPER_MODEL_IDS
    assert "medium-q5_0" in WHISPER_MODEL_IDS


def test_download_urls_point_at_ggerganov_whisper_cpp() -> None:
    url = whisper_download_url("small")
    assert url.startswith("https://huggingface.co/ggerganov/whisper.cpp/")
    assert url.endswith("ggml-small.bin")


def test_unknown_id_refuses() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        whisper_ggml_filename("not-real")


def test_presence_requires_ggml_bin(tmp_path: Path) -> None:
    assert is_whisper_model_present(tmp_path, "tiny") is False
    path = whisper_model_path(tmp_path, "tiny")
    path.write_bytes(b"x" * 2000)
    assert is_whisper_model_present(tmp_path, "tiny") is True


def test_download_skips_network_when_present(tmp_path: Path) -> None:
    path = whisper_model_path(tmp_path, "base")
    path.write_bytes(b"weights" * 400)
    beats: list[tuple[str, int, int | None, bool | None]] = []
    entry = download_whisper_model(
        "base", tmp_path, lambda f, r, t, v: beats.append((f, r, t, v))
    )
    assert entry["file"] == "ggml-base.bin"
    assert beats[-1][3] is True
