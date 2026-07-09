"""Lightweight voice embeddings for speaker identity and loopback diarization.

Uses log-magnitude spectral features (numpy only) — no extra model downloads.
Enrollment stores one profile; loopback segments cluster into numbered speakers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE

_EMBEDDING_DIM = 32
_FRAME_SAMPLES = 512
_HOP_SAMPLES = 256
_MATCH_THRESHOLD = 0.82
_NEW_SPEAKER_THRESHOLD = 0.72


def _frame_features(frame: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    windowed = frame * np.hanning(len(frame)).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(windowed))
    log_mag = np.log1p(spectrum[:_EMBEDDING_DIM]).astype(np.float32)
    norm = float(np.linalg.norm(log_mag))
    if norm > 1e-8:
        log_mag /= norm
    return log_mag


def extract_voice_embedding(audio: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Mean spectral embedding for one speech segment (16 kHz mono float32)."""
    if audio.size < _FRAME_SAMPLES:
        padded = np.zeros(_FRAME_SAMPLES, dtype=np.float32)
        padded[: audio.size] = audio
        audio = padded
    vectors: list[npt.NDArray[np.float32]] = []
    for start in range(0, max(1, audio.size - _FRAME_SAMPLES + 1), _HOP_SAMPLES):
        chunk = audio[start : start + _FRAME_SAMPLES]
        if chunk.size < _FRAME_SAMPLES:
            break
        vectors.append(_frame_features(chunk))
    if not vectors:
        return np.zeros(_EMBEDDING_DIM, dtype=np.float32)
    mean = np.mean(np.stack(vectors, axis=0), axis=0).astype(np.float32)
    norm = float(np.linalg.norm(mean))
    if norm > 1e-8:
        mean /= norm
    return mean


def cosine_similarity(a: npt.NDArray[np.float32], b: npt.NDArray[np.float32]) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    return float(np.dot(a, b))


def embedding_to_json(embedding: npt.NDArray[np.float32]) -> str:
    return json.dumps([round(float(v), 6) for v in embedding.tolist()])


def embedding_from_json(raw: str) -> npt.NDArray[np.float32] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    try:
        vector = np.array([float(v) for v in parsed], dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if vector.size == 0:
        return None
    norm = float(np.linalg.norm(vector))
    if norm > 1e-8:
        vector /= norm
    return vector


def decode_wav_pcm16_mono_16k(wav_bytes: bytes) -> npt.NDArray[np.float32]:
    """Decode a minimal PCM16 mono WAV blob to float32 at 16 kHz."""
    if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise ValueError("expected a PCM WAV file")
    channels = int.from_bytes(wav_bytes[22:24], "little")
    sample_rate = int.from_bytes(wav_bytes[24:28], "little")
    bits = int.from_bytes(wav_bytes[34:36], "little")
    if channels != 1 or bits != 16:
        raise ValueError("WAV must be mono 16-bit PCM")
    data_offset = wav_bytes.find(b"data")
    if data_offset < 0:
        raise ValueError("WAV data chunk missing")
    pcm = wav_bytes[data_offset + 8 :]
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if sample_rate != PIPELINE_SAMPLE_RATE:
        # Simple linear resample for enrollment clips (short).
        ratio = PIPELINE_SAMPLE_RATE / sample_rate
        new_len = max(1, int(math.floor(samples.size * ratio)))
        x_old = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
        samples = np.interp(x_new, x_old, samples).astype(np.float32)
    return samples


@dataclass
class LoopbackSpeakerDiarizer:
    """Assign numbered speaker ids on the loopback stream."""

    enrollment: npt.NDArray[np.float32] | None = None
    _centroids: dict[str, npt.NDArray[np.float32]] = field(default_factory=dict)
    _next_id: int = 1

    def assign(self, audio: npt.NDArray[np.float32]) -> str:
        embedding = extract_voice_embedding(audio)
        if self.enrollment is not None:
            if cosine_similarity(embedding, self.enrollment) >= _MATCH_THRESHOLD:
                return "me"
        best_id: str | None = None
        best_score = -1.0
        for speaker_id, centroid in self._centroids.items():
            score = cosine_similarity(embedding, centroid)
            if score > best_score:
                best_score = score
                best_id = speaker_id
        if best_id is not None and best_score >= _NEW_SPEAKER_THRESHOLD:
            # Running average keeps centroids stable across long meetings.
            old = self._centroids[best_id]
            updated = (old + embedding) / 2.0
            norm = float(np.linalg.norm(updated))
            if norm > 1e-8:
                updated /= norm
            self._centroids[best_id] = updated.astype(np.float32)
            return best_id
        speaker_id = str(self._next_id)
        self._next_id += 1
        self._centroids[speaker_id] = embedding
        return speaker_id


def resolve_speaker_label(speaker_id: str, identity_name: str) -> str:
    """Map a stored speaker_id to UI-facing text."""
    trimmed = identity_name.strip()
    if speaker_id == "me":
        return trimmed if trimmed else "Me"
    if speaker_id.isdigit():
        return f"Speaker {speaker_id}"
    return speaker_id


@dataclass
class SpeakerSessionLabeler:
    """Per-capture speaker assignment using enrollment + loopback clustering."""

    identity_name: str
    diarizer: LoopbackSpeakerDiarizer

    @classmethod
    def from_settings(cls, identity_name: str, enrollment_json: str) -> SpeakerSessionLabeler:
        enrollment = embedding_from_json(enrollment_json) if enrollment_json.strip() else None
        return cls(
            identity_name=identity_name.strip() or "Me",
            diarizer=LoopbackSpeakerDiarizer(enrollment=enrollment),
        )

    def me_labels(self) -> tuple[str, str]:
        return "me", resolve_speaker_label("me", self.identity_name)

    def assign_them(self, audio: npt.NDArray[np.float32]) -> tuple[str, str]:
        speaker_id = self.diarizer.assign(audio)
        return speaker_id, resolve_speaker_label(speaker_id, self.identity_name)

    def them_partial_label(self, speaker_id: str | None) -> tuple[str, str]:
        sid = speaker_id if speaker_id is not None else "1"
        return sid, resolve_speaker_label(sid, self.identity_name)
