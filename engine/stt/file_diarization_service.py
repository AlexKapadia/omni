"""Offline file speaker diarization using lightweight embeddings."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE
from engine.stt.speaker_voice_profile import LoopbackSpeakerDiarizer, resolve_speaker_label
from engine.stt.stt_backend_protocol import SttSegment


def assign_speakers_to_segments(
    samples: npt.NDArray[np.float32],
    segments: list[SttSegment],
    *,
    identity_name: str = "Me",
) -> list[tuple[SttSegment, str, str]]:
    """Return segments with (segment, speaker_id, speaker_label)."""
    diarizer = LoopbackSpeakerDiarizer()
    labeled: list[tuple[SttSegment, str, str]] = []
    for segment in segments:
        start = max(0, int(segment.t_start * PIPELINE_SAMPLE_RATE))
        end = min(samples.size, int(segment.t_end * PIPELINE_SAMPLE_RATE))
        if end <= start:
            speaker_id = "1"
        else:
            speaker_id = diarizer.assign(samples[start:end])
        label = resolve_speaker_label(speaker_id, identity_name)
        labeled.append((segment, speaker_id, label))
    return labeled
