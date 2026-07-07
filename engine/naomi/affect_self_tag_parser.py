"""Engine-side parser for the LLM's leading affect self-tag.

Purpose: the response stream opens with ``<<affect v=+0.6 a=0.7
burst=laugh?>>`` (docs/design/naomi-visual-brief.md §3). The engine parses
it BEFORE anything reaches Cartesia or the UI: the tag becomes the
(valence, arousal, burst) triple driving Cartesia emotion controls and the
pool uniforms, and the remaining text is what gets spoken/displayed.
Mirrors apps/ui/src/naomi/naomi-affect-tag-parser.ts exactly (same bounded
patterns, same clamps) so both sides agree on every input.
Pipeline position: called by ``voice_answer_service`` on the raw synthesis
completion, before clause chunking and TTS dispatch.

Security posture (claude.md §5.6 prompt-injection discipline): the tag
rides inside MODEL OUTPUT, downstream of untrusted transcript/document
content. Therefore this parser:
- never raises (malformed → None → neutral fallback, fail open to neutral);
- never returns any substring of the tag for display or TTS — malformed
  tag text is STILL stripped whenever it structurally looks like a tag;
- uses bounded quantifiers only, so hostile input cannot cause unbounded
  regex work.
"""

import re
from dataclasses import dataclass

# The tag must open the response (whitespace tolerated). Bounded quantifiers
# throughout — no catastrophic backtracking on hostile input.
_TAG_PATTERN = re.compile(r"^\s{0,16}<<\s{0,8}affect\b([^>]{0,160})>>", re.IGNORECASE)
# An UNCLOSED "<<affect ..." prefix must never flow into TTS — strip to the
# end of its line instead (never speak tag syntax).
_UNCLOSED_TAG_PATTERN = re.compile(r"^\s{0,16}<<\s{0,8}affect\b[^\n]{0,200}", re.IGNORECASE)
_VALENCE_PATTERN = re.compile(r"\bv\s{0,4}=\s{0,4}([+-]?\d{0,6}(?:\.\d{1,6})?)", re.IGNORECASE)
_AROUSAL_PATTERN = re.compile(r"\ba\s{0,4}=\s{0,4}([+-]?\d{0,6}(?:\.\d{1,6})?)", re.IGNORECASE)
_BURST_PATTERN = re.compile(
    r"\bburst\s{0,4}=\s{0,4}(laugh)\b\s{0,4}(?:\(\s{0,4}([+-]?\d{0,6}(?:\.\d{1,6})?)\s{0,4}\))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedAffect:
    """The clamped affect triple (brief §2 contract): v∈[-1,1], a∈[0,1],
    burst intensity ∈[0,1] or None when there is no laugh burst."""

    valence: float
    arousal: float
    burst_laugh_intensity: float | None = None

    def as_cartesia_tuple(self) -> tuple[float, float]:
        """The (v, a) pair the Cartesia framing quantizes to emotion+speed."""
        return (self.valence, self.arousal)

    def as_wire_triple(self) -> tuple[float, float, str | None]:
        """The reply-event shape: (v, a, burst-name-or-None)."""
        return (
            self.valence,
            self.arousal,
            "laugh" if self.burst_laugh_intensity is not None else None,
        )


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _parse_float(text: str | None) -> float | None:
    """Bounded float parse: None on anything non-numeric (never raises)."""
    if text is None or not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    # NaN/inf cannot come out of the bounded digit pattern, but guard anyway
    # (fail closed on garbage confidence — same posture as the VAD gate).
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def parse_leading_affect_tag(raw: object) -> tuple[ParsedAffect | None, str]:
    """Parse (and strip) a leading affect tag from one model completion.

    Returns ``(affect_or_None, text)`` where ``text`` is ALWAYS safe for TTS
    and display (any structural tag opener is removed even when malformed).
    NEVER raises; a non-string input yields ``(None, "")`` (fail closed).
    """
    if not isinstance(raw, str):
        return None, ""
    match = _TAG_PATTERN.match(raw)
    if match is None:
        unclosed = _UNCLOSED_TAG_PATTERN.match(raw)
        if unclosed is not None:
            return None, raw[unclosed.end() :].lstrip()
        return None, raw
    body = match.group(1) or ""
    remainder = raw[match.end() :].lstrip()
    valence = _parse_float(_valence_text(body))
    arousal = _parse_float(_arousal_text(body))
    # Both axes must be real numbers; otherwise the tag is malformed and the
    # caller uses the neutral fallback (fail open to neutral, per the brief).
    if valence is None or arousal is None:
        return None, remainder
    burst_match = _BURST_PATTERN.search(body)
    burst_intensity: float | None = None
    if burst_match is not None:
        parsed_intensity = _parse_float(burst_match.group(2))
        # `burst=laugh` without a parenthesised intensity = a full laugh.
        burst_intensity = _clamp(parsed_intensity if parsed_intensity is not None else 1.0, 0, 1)
    return (
        ParsedAffect(
            valence=_clamp(valence, -1, 1),
            arousal=_clamp(arousal, 0, 1),
            burst_laugh_intensity=burst_intensity,
        ),
        remainder,
    )


def _valence_text(body: str) -> str | None:
    match = _VALENCE_PATTERN.search(body)
    return match.group(1) if match is not None else None


def _arousal_text(body: str) -> str | None:
    match = _AROUSAL_PATTERN.search(body)
    return match.group(1) if match is not None else None
