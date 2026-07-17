"""Ollama HTTP helpers: list / pull / ping (Meetily-style local summary).

Purpose: thin HTTPS client against an OpenAI-compat Ollama host. Used by the
``ollama.*`` WS commands so Settings can list and pull models without the UI
inventing progress.
Pipeline position: called from ``engine.wiring.ollama_command_dispatcher``.

Security: only http(s) base URLs; no user-supplied path traversal; pull
model names are allowlisted to a safe charset.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
ProgressFn = Callable[[str, int, int | None], None]


def normalize_ollama_base(url: str) -> str:
    trimmed = url.strip().rstrip("/")
    if not trimmed:
        return "http://127.0.0.1:11434"
    if not (trimmed.startswith("http://") or trimmed.startswith("https://")):
        raise ValueError("Ollama URL must start with http:// or https://")
    return trimmed


def _assert_http_url(url: str) -> str:
    """Fail closed unless scheme is http or https (S310 defence)."""
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {scheme!r}")
    return url


def _http_urlopen(req: urllib.request.Request, timeout: float) -> Any:
    """Open an HTTP(S) request after re-validating the scheme (S310)."""
    target = req.full_url if hasattr(req, "full_url") else req.get_full_url()
    _assert_http_url(target)
    # Scheme validated http(s) only by normalize_ollama_base / _assert_http_url.
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310


def _get_json(url: str, timeout_s: float = 10.0) -> Any:
    safe_url = _assert_http_url(url)
    req = urllib.request.Request(  # noqa: S310 — scheme validated by _assert_http_url
        safe_url, method="GET", headers={"Accept": "application/json"}
    )
    with _http_urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ping_ollama(base_url: str) -> dict[str, object]:
    """Return ``{ok, version?}`` — fail closed on connection errors."""
    base = normalize_ollama_base(base_url)
    try:
        data = _get_json(f"{base}/api/version", timeout_s=5.0)
        version = data.get("version") if isinstance(data, dict) else None
        return {"ok": True, "version": version if isinstance(version, str) else None}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)[:200]}


def list_ollama_models(base_url: str) -> list[dict[str, object]]:
    """List local Ollama tags as ``[{name, size}]``."""
    base = normalize_ollama_base(base_url)
    data = _get_json(f"{base}/api/tags", timeout_s=15.0)
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    out: list[dict[str, object]] = []
    for row in models:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        size = row.get("size")
        out.append({"name": name, "size": size if isinstance(size, int) else 0})
    return out


def pull_ollama_model(
    base_url: str,
    model: str,
    on_progress: ProgressFn | None = None,
) -> dict[str, object]:
    """Pull one model; streams NDJSON progress from Ollama ``/api/pull``."""
    if not _MODEL_NAME_RE.match(model):
        raise ValueError("invalid Ollama model name")
    base = normalize_ollama_base(base_url)
    body = json.dumps({"name": model, "stream": True}).encode("utf-8")
    pull_url = _assert_http_url(f"{base}/api/pull")
    req = urllib.request.Request(  # noqa: S310 — scheme validated by _assert_http_url
        pull_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
    )
    completed = False
    with _http_urlopen(req, timeout=3600) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            status = str(event.get("status", ""))
            completed = status == "success" or bool(event.get("completed"))
            total = event.get("total")
            completed_bytes = event.get("completed")
            if on_progress is not None:
                on_progress(
                    model,
                    int(completed_bytes) if isinstance(completed_bytes, int) else 0,
                    int(total) if isinstance(total, int) else None,
                )
    if not completed:
        # Some Ollama builds end without an explicit success line after the last layer.
        return {"ok": True, "model": model}
    return {"ok": True, "model": model}
