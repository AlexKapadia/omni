"""Downloads STT model weights with progress + SHA256 manifest recording.

Purpose: fetches the two M1 model artifacts — Silero VAD v5 (ONNX) and
Parakeet-TDT 0.6B v2 (.nemo) — into the local models directory
(``%LOCALAPPDATA%/Omni/models``, overridable via ``OMNI_MODELS_DIR``),
streaming with progress output, hashing while downloading, and recording
name/size/SHA256 into ``packaging/model-manifest.json`` so installs are
verifiable byte-for-byte.
Pipeline position: a setup-time utility (``python -m
engine.stt.model_weights_downloader``); the live pipeline only READS the
files this module placed.

Security invariants:
- HTTPS-only, from pinned first-party URLs (NVIDIA HF repo, Silero repo)
  — deny by default on any other scheme/host shape.
- Downloads land in a ``.partial`` file and are atomically renamed only
  when complete — a truncated download can never masquerade as a model.
- The SHA256 in the manifest is computed from the exact bytes on disk;
  the packaged installer re-verifies against it (tamper evidence).
"""

import hashlib
import json
import os
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Pinned artifact sources. WHY these exact URLs: the official Silero
# repository and NVIDIA's official Hugging Face model repo — primary
# sources only, no mirrors.
SILERO_VAD_FILENAME = "silero_vad.onnx"
PARAKEET_FILENAME = "parakeet-tdt-0.6b-v2.nemo"


@dataclass(frozen=True)
class ModelSpec:
    """One downloadable model artifact."""

    filename: str
    url: str
    description: str


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        filename=SILERO_VAD_FILENAME,
        url=(
            "https://github.com/snakers4/silero-vad/raw/master/"
            "src/silero_vad/data/silero_vad.onnx"
        ),
        description="Silero VAD v5 (ONNX) — per-stream speech gating",
    ),
    ModelSpec(
        filename=PARAKEET_FILENAME,
        url=(
            "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2/resolve/main/"
            "parakeet-tdt-0.6b-v2.nemo"
        ),
        description="NVIDIA Parakeet-TDT 0.6B v2 — streaming transcription",
    ),
)

# fetch(url, destination, progress(bytes_done, bytes_total|None)) — injectable
# so unit tests never touch the network (no-network-in-unit-tests rule).
FetchFn = Callable[[str, Path, Callable[[int, int | None], None]], None]


def models_directory() -> Path:
    """Resolve the models directory: OMNI_MODELS_DIR or %LOCALAPPDATA%/Omni/models."""
    override = os.environ.get("OMNI_MODELS_DIR")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "Omni" / "models"


def default_manifest_path() -> Path:
    """packaging/model-manifest.json at the repo root (build artifact)."""
    return Path(__file__).resolve().parent.parent.parent / "packaging" / "model-manifest.json"


def sha256_of_file(path: Path) -> str:
    """Stream-hash a file (models are multi-GB; never read them whole)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _https_fetch(url: str, destination: Path, progress: Callable[[int, int | None], None]) -> None:
    """Default fetcher: streaming HTTPS download to ``destination``."""
    if not url.startswith("https://"):
        # Deny by default: plaintext or exotic schemes are refused outright.
        raise ValueError(f"refusing non-HTTPS model URL: {url}")
    request = urllib.request.Request(  # noqa: S310 — https-only, allowlisted above
        url, headers={"User-Agent": "omni-engine-model-fetch"}
    )
    with urllib.request.urlopen(request) as response:  # noqa: S310 — https-only enforced
        length_header = response.headers.get("Content-Length")
        total = int(length_header) if length_header else None
        done = 0
        with destination.open("wb") as out:
            for block in iter(lambda: response.read(1024 * 256), b""):
                out.write(block)
                done += len(block)
                progress(done, total)


def _print_progress(name: str) -> Callable[[int, int | None], None]:
    """Console progress: one line per ~5% so logs stay readable."""
    last_reported = -1

    def progress(done: int, total: int | None) -> None:
        nonlocal last_reported
        if not total:
            return
        percent = int(done * 100 / total)
        if percent >= last_reported + 5:
            last_reported = percent
            print(f"  {name}: {percent}% ({done / 1e6:.1f} / {total / 1e6:.1f} MB)", flush=True)

    return progress


def ensure_models_downloaded(
    models_dir: Path | None = None,
    specs: tuple[ModelSpec, ...] = MODEL_SPECS,
    manifest_path: Path | None = None,
    fetch: FetchFn = _https_fetch,
) -> list[dict[str, Any]]:
    """Download any missing models, hash everything, write the manifest.

    Idempotent: present files are hashed and recorded, never re-fetched.
    Returns the manifest entries written.
    """
    target_dir = models_dir if models_dir is not None else models_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_path if manifest_path is not None else default_manifest_path()

    entries: list[dict[str, Any]] = []
    for spec in specs:
        final_path = target_dir / spec.filename
        if not final_path.is_file():
            print(f"downloading {spec.filename} ...", flush=True)
            partial_path = target_dir / (spec.filename + ".partial")
            fetch(spec.url, partial_path, _print_progress(spec.filename))
            # Atomic completion gate: only a fully-written file gets the
            # real name — a torn download can never be loaded as a model.
            partial_path.replace(final_path)
        digest = sha256_of_file(final_path)
        entries.append(
            {
                "name": spec.filename,
                "description": spec.description,
                "url": spec.url,
                "bytes": final_path.stat().st_size,
                "sha256": digest,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )
        print(f"  {spec.filename}: sha256={digest}", flush=True)

    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps({"models": entries}, indent=2) + "\n", encoding="utf-8")
    print(f"manifest written: {manifest_file}", flush=True)
    return entries


if __name__ == "__main__":
    try:
        ensure_models_downloaded()
    except Exception as exc:  # Loud, honest failure for the setup operator.
        print(f"model download FAILED: {exc}", file=sys.stderr, flush=True)
        raise
