"""Model downloader: SHA256 manifest correctness, idempotency, atomicity.

Uses an injected fake fetcher — no network ever (unit-test rule). The
SHA256 values asserted are independently computed in the test, so a wrong
hash in the manifest cannot self-validate.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from engine.stt.model_weights_downloader import (
    ModelSpec,
    _https_fetch,
    ensure_models_downloaded,
    sha256_of_file,
)

FAKE_BYTES = {
    "tiny_vad.onnx": b"onnx-model-bytes-\x00\x01\x02" * 100,
    "tiny_parakeet.nemo": b"nemo-model-bytes-\xff\xfe" * 5000,
}

SPECS = (
    ModelSpec("tiny_vad.onnx", "https://example.invalid/vad.onnx", "fake vad"),
    ModelSpec("tiny_parakeet.nemo", "https://example.invalid/parakeet.nemo", "fake stt"),
)


ProgressFn = Callable[[int, int | None], None]


def make_fake_fetch(counter: dict[str, int]) -> Callable[..., None]:
    def fake_fetch(url: str, destination: Path, progress: ProgressFn) -> None:
        name = url.rsplit("/", 1)[-1]
        payload = FAKE_BYTES["tiny_vad.onnx" if "vad" in name else "tiny_parakeet.nemo"]
        counter[url] = counter.get(url, 0) + 1
        destination.write_bytes(payload)
        progress(len(payload), len(payload))

    return fake_fetch


def test_manifest_records_independently_verifiable_sha256_and_sizes(tmp_path: Path) -> None:
    manifest_path = tmp_path / "packaging" / "model-manifest.json"
    entries = ensure_models_downloaded(
        models_dir=tmp_path / "models",
        specs=SPECS,
        manifest_path=manifest_path,
        fetch=make_fake_fetch({}),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["models"] == entries
    by_name = {entry["name"]: entry for entry in entries}
    for filename, payload in FAKE_BYTES.items():
        expected_sha = hashlib.sha256(payload).hexdigest()  # Independent computation.
        assert by_name[filename]["sha256"] == expected_sha
        assert by_name[filename]["bytes"] == len(payload)
        # The file on disk matches the manifest byte-for-byte.
        assert (tmp_path / "models" / filename).read_bytes() == payload


def test_second_run_is_idempotent_and_never_refetches(tmp_path: Path) -> None:
    counter: dict[str, int] = {}
    models_dir = tmp_path / "models"
    manifest_path = tmp_path / "model-manifest.json"
    first = ensure_models_downloaded(
        models_dir=models_dir, specs=SPECS, manifest_path=manifest_path,
        fetch=make_fake_fetch(counter),
    )
    second = ensure_models_downloaded(
        models_dir=models_dir, specs=SPECS, manifest_path=manifest_path,
        fetch=make_fake_fetch(counter),
    )
    assert all(count == 1 for count in counter.values()), "a present file was refetched"
    assert [e["sha256"] for e in first] == [e["sha256"] for e in second]


def test_failed_download_leaves_no_final_file_atomicity(tmp_path: Path) -> None:
    """A fetch that dies mid-stream must never leave a loadable model file."""

    def dying_fetch(url: str, destination: Path, progress: ProgressFn) -> None:
        destination.write_bytes(b"half a model")  # Partial bytes land...
        raise ConnectionError("network died mid-download")

    with pytest.raises(ConnectionError):
        ensure_models_downloaded(
            models_dir=tmp_path / "models",
            specs=SPECS[:1],
            manifest_path=tmp_path / "model-manifest.json",
            fetch=dying_fetch,
        )
    assert not (tmp_path / "models" / "tiny_vad.onnx").exists()  # No torn model.
    assert not (tmp_path / "model-manifest.json").exists()  # No lying manifest.


def test_https_fetcher_refuses_non_https_schemes(tmp_path: Path) -> None:
    """Deny by default: http://, file://, ftp:// are all rejected outright."""
    for url in ("http://example.com/m.onnx", "file:///etc/passwd", "ftp://x/y"):
        with pytest.raises(ValueError, match="non-HTTPS"):
            _https_fetch(url, tmp_path / "out.bin", lambda done, total: None)


def test_sha256_of_file_streams_correctly(tmp_path: Path) -> None:
    """Hash of a multi-megabyte file matches hashlib over the same bytes."""
    payload = bytes(range(256)) * 8192  # 2 MiB, all byte values.
    target = tmp_path / "blob.bin"
    target.write_bytes(payload)
    assert sha256_of_file(target) == hashlib.sha256(payload).hexdigest()


def test_models_directory_respects_omni_models_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engine.stt.model_weights_downloader import models_directory

    monkeypatch.setenv("OMNI_MODELS_DIR", str(tmp_path / "custom"))
    assert models_directory() == tmp_path / "custom"
    monkeypatch.delenv("OMNI_MODELS_DIR")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    assert models_directory() == tmp_path / "lad" / "Omni" / "models"
