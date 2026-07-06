"""LIVE smoke test: real engine, real models, real loopback audio route.

Marked ``live_stt`` (deselected by default): boots the actual engine
process with the real Parakeet + Silero models, plays a locally
synthesised Windows-SAPI speech WAV through the DEFAULT OUTPUT device
while WASAPI loopback captures it, and asserts genuine
``transcript.final`` events arrive on stream "them" with lag under 3 s.

No network is used: SAPI TTS is an offline OS feature and the models are
already on disk. Run explicitly with: ``uv run pytest -m live_stt -s``.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from engine.stt.model_weights_downloader import (
    PARAKEET_FILENAME,
    SILERO_VAD_FILENAME,
    models_directory,
)

pytestmark = pytest.mark.live_stt

PORT = 8899
SPOKEN_SENTENCE = (
    "The quick brown fox jumps over the lazy dog while the meeting "
    "transcript appears on screen in real time."
)
# Words that must survive transcription for the smoke to count as real.
EXPECTED_KEYWORDS = ("fox", "meeting", "transcript")


def _models_present() -> bool:
    directory = models_directory()
    return (directory / SILERO_VAD_FILENAME).is_file() and (
        directory / PARAKEET_FILENAME
    ).is_file()


requires_live_stack = pytest.mark.skipif(
    sys.platform != "win32" or not _models_present(),
    reason="live smoke needs Windows audio + downloaded models",
)


@pytest.fixture()
def speech_wav(tmp_path: Path) -> Path:
    """Synthesise the spoken sentence with offline Windows SAPI TTS."""
    wav_path = tmp_path / "spoken_sentence.wav"
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{wav_path}'); "
        f"$s.Speak('{SPOKEN_SENTENCE}'); $s.Dispose()"
    )
    subprocess.run(  # noqa: S603 — fixed local command, no untrusted input.
        ["powershell", "-NoProfile", "-Command", script],  # noqa: S607
        check=True,
        capture_output=True,
        timeout=60,
    )
    assert wav_path.is_file() and wav_path.stat().st_size > 10_000
    return wav_path


def _spawn_engine(db_path: Path, log_path: Path) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "OMNI_ENGINE_PORT": str(PORT),
            "OMNI_DB_PATH": str(db_path),
        }
    )
    # Log to a FILE, never a pipe: NeMo's model-load logging exceeds the OS
    # pipe buffer and an unread pipe would deadlock the engine mid-startup.
    log_handle = log_path.open("wb")
    return subprocess.Popen(
        [sys.executable, "-m", "engine.server"],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )


def _wait_for_health(timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/health", timeout=2
            ) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise AssertionError("engine /health never came up")


def _play_through_default_output(wav_path: Path) -> threading.Thread:
    import winsound

    thread = threading.Thread(
        target=winsound.PlaySound, args=(str(wav_path), winsound.SND_FILENAME)
    )
    thread.start()
    return thread


async def _run_capture_session(speech_wav: Path) -> tuple[list[dict[str, Any]], float]:
    """Drive the WS protocol; returns ('them' finals, seconds until ready)."""
    import websockets

    ready_started = time.monotonic()
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws", max_size=2**22) as ws:
        # 1. Wait for stt_ready=true in the heartbeat (model load can take a while).
        while True:
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=300))
            if frame["name"] == "engine.heartbeat" and frame["payload"]["stt_ready"]:
                break
        ready_seconds = time.monotonic() - ready_started

        # 2. capture.start -> ok reply.
        await ws.send(
            json.dumps(
                {
                    "v": 1,
                    "kind": "command",
                    "name": "capture.start",
                    "id": "live-smoke-start",
                    "payload": {"title": "Live smoke test"},
                }
            )
        )
        while True:
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if frame["kind"] == "reply":
                assert frame["name"] == "ok", f"capture.start failed: {frame}"
                break

        # 3. Play the sentence out of the default speakers; loopback hears it.
        player = _play_through_default_output(speech_wav)

        # 4. Collect transcript events until finals arrive (or timeout).
        finals: list[dict[str, Any]] = []
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            try:
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except TimeoutError:
                continue
            if frame["name"] == "transcript.final" and frame["payload"]["stream"] == "them":
                finals.append(frame["payload"])
            if finals and not player.is_alive():
                break
        player.join(timeout=30)

        # 5. capture.stop -> ok reply.
        await ws.send(
            json.dumps(
                {
                    "v": 1,
                    "kind": "command",
                    "name": "capture.stop",
                    "id": "live-smoke-stop",
                    "payload": {},
                }
            )
        )
        while True:
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if frame["kind"] == "reply":
                assert frame["name"] == "ok", f"capture.stop failed: {frame}"
                break
    return finals, ready_seconds


@requires_live_stack
def test_live_loopback_capture_transcribes_real_audio(
    speech_wav: Path, tmp_path: Path
) -> None:
    engine_log = Path(
        os.environ.get("OMNI_SMOKE_LOG_DIR", str(tmp_path))
    ) / "engine-live-smoke.log"
    engine = _spawn_engine(tmp_path / "live-smoke.db", engine_log)
    try:
        _wait_for_health(timeout_s=120.0)
        finals, ready_seconds = asyncio.run(_run_capture_session(speech_wav))
    finally:
        engine.terminate()
        engine.wait(timeout=15)

    if not finals:  # Surface the engine's own account before failing.
        tail = engine_log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
        print("\n".join(["--- engine log tail ---", *tail]))
    assert finals, "no transcript.final arrived on stream 'them'"
    combined_text = " ".join(f["text"] for f in finals).lower()
    lags = [f["lag_ms"] for f in finals]
    # Human-readable evidence for the smoke report (-s to see it).
    print(f"\nSTT ready after {ready_seconds:.1f} s")
    print(f"TRANSCRIPT ({len(finals)} final(s)): {combined_text!r}")
    print(f"lag_ms per final: {[round(lag) for lag in lags]}")

    matched = [k for k in EXPECTED_KEYWORDS if k in combined_text]
    assert matched, f"transcript {combined_text!r} matched none of {EXPECTED_KEYWORDS}"
    assert min(lags) < 3000, f"finalisation lag too high: {lags}"
