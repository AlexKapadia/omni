"""The [n]-marker ↔ retrieved-chunk contract: context numbering + mapping.

Purpose: one place owns how chunks become the numbered context block the
model sees, and how the model's inline ``[n]`` markers map back onto those
chunks — so a marker in the rendered answer can NEVER point at nothing.
Pipeline position: used by ``ask_omni_answer_service`` between retrieval
and the returned :class:`AskAnswer`.

Exactness invariants (tested):
- Source numbering is the chunk order, 1-based: context source ``[i]`` IS
  ``chunks[i-1]``, and a citation with ``n = i`` quotes exactly that chunk.
- Dangling markers (n < 1 or n > len(chunks)) are STRIPPED from the answer
  text deterministically — never rendered, never cited.
- Citations are emitted only for markers that actually appear in the
  answer, ascending by n, one per n (no duplicates, no dangling entries).

Security note: chunk text and answer text are untrusted data — they are
regex-scanned and string-built only, never interpreted.
"""

import re

from engine.ask.ask_answer_contracts import AskCitation
from engine.index.retrieved_chunk_types import RetrievedChunk

# Deterministic quote/snippet truncation for payloads: enough to verify the
# fact in the UI without shipping whole notes over the wire.
MAX_QUOTE_CHARS = 320
TRUNCATION_SUFFIX = "…"

_CITATION_MARKER = re.compile(r"\[(\d+)\]")


def truncate_quote(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    """Deterministic truncation: verbatim prefix + ellipsis when over limit."""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX


def build_numbered_context(chunks: list[RetrievedChunk]) -> str:
    """Render chunks as the numbered source block the synthesis model reads.

    Format per source (stable, tested): a ``[i]`` header carrying the exact
    citation string and heading breadcrumb, then the chunk text verbatim.
    The chunk ORDER defines the marker numbering — nothing else does.
    """
    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        # The breadcrumb separator matches the UI's rendering, not ">".
        heading = f" › {chunk.heading_path}" if chunk.heading_path else ""  # noqa: RUF001
        blocks.append(f"[{index}] {chunk.citation}{heading}\n{chunk.text.strip()}")
    return "\n\n".join(blocks)


def extract_citation_markers(answer_text: str) -> list[int]:
    """Marker numbers in order of first appearance, deduplicated."""
    seen: list[int] = []
    for match in _CITATION_MARKER.finditer(answer_text):
        value = int(match.group(1))
        if value not in seen:
            seen.append(value)
    return seen


def strip_dangling_markers(answer_text: str, chunk_count: int) -> str:
    """Remove every ``[n]`` whose n does not map to a provided chunk.

    A model-invented marker must never render: a citation pointing at
    nothing would be a fabricated source (fail honest). Whitespace directly
    before a stripped marker is collapsed so no double spaces remain.
    """

    def _replace(match: re.Match[str]) -> str:
        value = int(match.group(1))
        return match.group(0) if 1 <= value <= chunk_count else ""

    stripped = _CITATION_MARKER.sub(_replace, answer_text)
    return re.sub(r" +(?=[ .,;:!?\n])", "", stripped)


def citations_for_answer(
    chunks: list[RetrievedChunk], answer_text: str
) -> tuple[AskCitation, ...]:
    """Build the citation list for exactly the markers the answer uses.

    ``answer_text`` must already have dangling markers stripped; any marker
    found here therefore maps 1:1 onto ``chunks[n-1]``. Ascending by n.
    """
    citations: list[AskCitation] = []
    for n in sorted(extract_citation_markers(answer_text)):
        if not 1 <= n <= len(chunks):  # defence in depth: never index out
            continue
        chunk = chunks[n - 1]
        citations.append(
            AskCitation(
                n=n,
                note_path=chunk.note_path,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                heading_path=chunk.heading_path,
                quote=truncate_quote(chunk.text),
            )
        )
    return tuple(citations)
