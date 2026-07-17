"""Ollama HTTP helpers: ping/list/pull — no network (urlopen is monkeypatched)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from engine.router.ollama_http_client import (
    list_ollama_models,
    normalize_ollama_base,
    ping_ollama,
    pull_ollama_model,
)


class _FakeResponse:
    """A minimal urlopen()-context-manager stand-in (no real socket)."""

    def __init__(self, payload: bytes = b"", lines: list[bytes] | None = None) -> None:
        self._payload = payload
        self._lines = lines or []

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self) -> object:  # NDJSON streaming body
        return iter(self._lines)


def test_normalize_ollama_base_defaults_trims_and_validates_scheme() -> None:
    assert normalize_ollama_base("") == "http://127.0.0.1:11434"
    assert normalize_ollama_base("   ") == "http://127.0.0.1:11434"
    assert normalize_ollama_base("http://host:11434/") == "http://host:11434"
    with pytest.raises(ValueError):
        normalize_ollama_base("ftp://host")


def test_ping_ollama_reports_ok_and_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(json.dumps({"version": "0.5.1"}).encode("utf-8"))

    monkeypatch.setattr("engine.router.ollama_http_client.urllib.request.urlopen", fake_urlopen)
    assert ping_ollama("http://127.0.0.1:11434") == {"ok": True, "version": "0.5.1"}


def test_ping_ollama_fails_closed_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("engine.router.ollama_http_client.urllib.request.urlopen", fake_urlopen)
    result = ping_ollama("http://127.0.0.1:11434")
    assert result["ok"] is False
    assert "connection refused" in str(result["error"])


def test_ping_ollama_tolerates_a_missing_version_field(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(json.dumps({}).encode("utf-8"))

    monkeypatch.setattr("engine.router.ollama_http_client.urllib.request.urlopen", fake_urlopen)
    assert ping_ollama("http://127.0.0.1:11434") == {"ok": True, "version": None}


def test_list_ollama_models_filters_malformed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "models": [
            {"name": "llama3.2", "size": 123},
            {"name": "", "size": 5},  # empty name -> skipped
            {"size": 5},  # missing name -> skipped
            "not-a-dict",  # non-dict row -> skipped
            {"name": "gemma3:1b"},  # missing size -> defaults to 0
        ]
    }

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("engine.router.ollama_http_client.urllib.request.urlopen", fake_urlopen)
    models = list_ollama_models("http://127.0.0.1:11434")
    assert models == [{"name": "llama3.2", "size": 123}, {"name": "gemma3:1b", "size": 0}]


def test_list_ollama_models_returns_empty_list_on_wrong_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(json.dumps({"models": "not-a-list"}).encode("utf-8"))

    monkeypatch.setattr("engine.router.ollama_http_client.urllib.request.urlopen", fake_urlopen)
    assert list_ollama_models("http://127.0.0.1:11434") == []


def test_pull_ollama_model_rejects_unsafe_model_names() -> None:
    """Deny by default: no urlopen call happens for a hostile model name."""
    with pytest.raises(ValueError):
        pull_ollama_model("http://127.0.0.1:11434", "../../etc/passwd")


def test_pull_ollama_model_rejects_empty_and_overlong_names() -> None:
    with pytest.raises(ValueError):
        pull_ollama_model("http://127.0.0.1:11434", "")
    with pytest.raises(ValueError):
        pull_ollama_model("http://127.0.0.1:11434", "a" * 129)


def test_pull_ollama_model_streams_progress_and_reports_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        {"status": "pulling manifest"},
        {"status": "downloading", "completed": 50, "total": 100},
        {"status": "success"},
    ]
    lines = [json.dumps(e).encode("utf-8") for e in events]

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(lines=lines)

    monkeypatch.setattr("engine.router.ollama_http_client.urllib.request.urlopen", fake_urlopen)
    beats: list[tuple[str, int, int | None]] = []

    def on_progress(model: str, done: int, total: int | None) -> None:
        beats.append((model, done, total))

    result = pull_ollama_model("http://127.0.0.1:11434", "llama3.2", on_progress)
    assert result == {"ok": True, "model": "llama3.2"}
    assert beats == [("llama3.2", 0, None), ("llama3.2", 50, 100), ("llama3.2", 0, None)]


def test_pull_ollama_model_tolerates_blank_and_malformed_ndjson_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = [
        b"",  # blank line: skipped
        b"not-json-at-all",  # malformed: skipped
        b'"just-a-string"',  # valid JSON, but not a dict: skipped
        json.dumps({"status": "success"}).encode("utf-8"),
    ]

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(lines=lines)

    monkeypatch.setattr("engine.router.ollama_http_client.urllib.request.urlopen", fake_urlopen)
    result = pull_ollama_model("http://127.0.0.1:11434", "llama3.2")
    assert result == {"ok": True, "model": "llama3.2"}


def test_pull_ollama_model_without_progress_callback_still_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``on_progress`` is optional — a caller that never asks for beats still
    gets an honest completion result."""
    lines = [json.dumps({"status": "success"}).encode("utf-8")]

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(lines=lines)

    monkeypatch.setattr("engine.router.ollama_http_client.urllib.request.urlopen", fake_urlopen)
    assert pull_ollama_model("http://127.0.0.1:11434", "llama3.2") == {
        "ok": True,
        "model": "llama3.2",
    }
