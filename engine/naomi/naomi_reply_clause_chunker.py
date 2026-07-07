"""Split Naomi's completed reply into clause chunks for streamed TTS.

Purpose: the tri-provider router has NO token-streaming surface (it returns
the whole synthesis at once), yet Cartesia CAN stream audio as text arrives.
To claw back time-to-first-audio we cut the finished reply at clause
boundaries and send the chunks as Cartesia ``continue:true`` frames (the
last with ``continue:false``): Naomi starts speaking the first clause while
the rest is still being framed. Streaming the router itself is the honest
follow-up (noted in the tracker); this is the pragmatic win today.
Pipeline position: called by ``engine.naomi.naomi_turn_orchestrator`` after
affect-tag stripping, feeding ``PersistentCartesiaConnection.speak_utterance``.

Correctness invariant (tested): ``"".join(chunks) == text`` EXACTLY — every
character, including whitespace and punctuation, is preserved and in order,
so the spoken transcript is byte-identical to the displayed reply (fidelity
mandate). Boundedness (tested): chunk count is O(len/​min_chars); no
degenerate one-character frames.
"""

# Clause-ending punctuation: a break is allowed AFTER one of these when the
# next character is whitespace or end-of-text (so "3.5" or "e.g." mid-word
# does not split). Ordered from strongest to weakest boundary.
_CLAUSE_PUNCTUATION = frozenset({".", "!", "?", ";", ":", ",", "—"})

# A chunk shorter than this never triggers a boundary break — it keeps
# accumulating so we do not emit a two-word frame. The trailing remainder is
# merged back if it lands under this length.
_DEFAULT_MIN_CHARS = 12
# A hard ceiling: past this length we break at the next whitespace even
# without punctuation, so one run-on sentence cannot become a single giant
# frame that defeats the streaming win.
_DEFAULT_MAX_CHARS = 180


def chunk_reply_into_clauses(
    text: str,
    *,
    min_chars: int = _DEFAULT_MIN_CHARS,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> tuple[str, ...]:
    """Cut ``text`` into ordered clause chunks whose concatenation IS ``text``.

    Returns ``()`` for empty or whitespace-only input (the caller decides
    what to do with a silent reply — it never reaches TTS). Otherwise the
    first chunk is a short leading clause (fast first audio) and the rest are
    clause- or length-bounded, with any tiny trailing fragment merged back so
    no frame is a lone scrap of punctuation.
    """
    if not text or text.isspace():
        return ()
    if max_chars < min_chars:  # defensive: a nonsensical config never crashes
        max_chars = min_chars

    chunks: list[str] = []
    start = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        current_length = index - start + 1
        next_is_space = index + 1 >= length or text[index + 1].isspace()
        at_clause_boundary = char in _CLAUSE_PUNCTUATION and next_is_space
        force_break = current_length >= max_chars and char.isspace()
        if (at_clause_boundary and current_length >= min_chars) or force_break:
            end = index + 1
            # Absorb the trailing whitespace into THIS chunk so the next chunk
            # starts on real content and the concatenation reconstructs text.
            while end < length and text[end].isspace():
                end += 1
            chunks.append(text[start:end])
            start = end
            index = end
            continue
        index += 1
    if start < length:
        chunks.append(text[start:])

    return _merge_short_tail(chunks, min_chars)


def _merge_short_tail(chunks: list[str], min_chars: int) -> tuple[str, ...]:
    """Fold a too-short final chunk into its predecessor (join is preserved).

    A trailing fragment (e.g. a closing "Yes.") can fall under ``min_chars``;
    merging it avoids a needless two-character continue frame. Concatenation
    is unchanged because merging is plain string joining.
    """
    if len(chunks) >= 2 and len(chunks[-1].strip()) < min_chars:
        tail = chunks.pop()
        chunks[-1] = chunks[-1] + tail
    return tuple(chunks)
