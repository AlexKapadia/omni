"""Tests for speaker voice profile and diarization."""

import numpy as np

from engine.stt.speaker_voice_profile import (
    LoopbackSpeakerDiarizer,
    cosine_similarity,
    extract_voice_embedding,
    resolve_speaker_label,
)


def test_resolve_speaker_label() -> None:
    assert resolve_speaker_label("me", "Alex") == "Alex"
    assert resolve_speaker_label("1", "Alex") == "Speaker 1"
    assert resolve_speaker_label("me", "") == "Me"


def test_diarizer_assigns_numbered_speakers() -> None:
    diarizer = LoopbackSpeakerDiarizer()
    rng = np.random.default_rng(0)
    a = np.sin(np.linspace(0, 40, 16_000)).astype(np.float32)
    b = rng.standard_normal(16_000).astype(np.float32)
    first = diarizer.assign(a)
    second = diarizer.assign(b)
    third = diarizer.assign(a)
    assert first == "1"
    assert second == "2"
    assert third == "1"
    assert cosine_similarity(extract_voice_embedding(a), extract_voice_embedding(a)) > 0.99
