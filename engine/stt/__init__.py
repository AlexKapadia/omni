"""VAD-gated streaming transcription for the Omni engine.

Purpose: turns the labelled 16 kHz audio frames produced by
``engine.audio`` into live transcript events — Silero VAD (ONNX) gates
each stream into speech segments, Parakeet-TDT transcribes overlapping
4 s windows, and the streaming chunk merger stitches windows into one
faithful word sequence per segment.
Pipeline position: second stage of the pipeline — consumes
``engine.audio`` frames, emits ``transcript.partial`` / ``transcript.final``
protocol events, and persists final segments via ``engine.storage``.

Security / fidelity invariants:
- Transcription fidelity (binding user mandate): the raw transcript is
  ground truth. NOTHING in this package substitutes, rewrites, or removes
  tokens the model produced — the merger only SELECTS and ORDERS tokens.
  Filler removal belongs to the enhancement layer, never here.
- Audio buffers are discarded after transcription (local-only invariant);
  model weights and inference stay entirely on this machine.
"""

from engine.stt.streaming_chunk_merger import StreamingChunkMerger
from engine.stt.vad_gating_state_machine import VadGateEvent, VadGatingStateMachine
from engine.stt.word_token_types import TranscribedWindow, WordToken

__all__ = [
    "StreamingChunkMerger",
    "TranscribedWindow",
    "VadGateEvent",
    "VadGatingStateMachine",
    "WordToken",
]
