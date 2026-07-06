"""Streaming chunk merger: stitches overlapping window transcriptions.

Purpose: the correctness-critical core of streaming STT. Audio is
transcribed in 4 s windows with 0.8 s overlap; every region inside an
overlap is heard TWICE, so the merger must pick exactly one copy of each
word — no duplicates, no drops — using word timestamps.

Merge rule (deterministic, documented contract):
- Windows are processed in ``index`` order; out-of-order arrivals are
  buffered until their turn (transcriptions can finish out of order).
- The cut between window N-1 and window N is the MIDPOINT of their
  overlap: ``cut = N.t_start + overlap/2``. Words are assigned by their
  temporal midpoint — before the cut the EARLIER window's copy wins,
  at/after the cut the LATER window's copy wins (it heard the region with
  more right-context). Because windows advance by a fixed hop, window
  N-1's trailing cut equals window N's leading cut, so every instant has
  exactly one owner.
- A boundary guard drops a literal duplicate straddling the cut: if the
  first token taken from the new window equals (casefold) the last
  committed token and their midpoints are within a small tolerance, the
  new copy is dropped — timestamp jitter between windows must not double
  a word.

Pipeline position: consumes ``TranscribedWindow``s from the transcriber,
feeds merged words to transcript.partial/final emission.

FIDELITY INVARIANT (binding user mandate): the merger only SELECTS and
ORDERS tokens — it never rewrites text, never drops disfluencies, never
"cleans". Every output token is one of the input tokens, verbatim.
"""

from engine.stt.word_token_types import TranscribedWindow, WordToken

# Two words straddling a cut are "the same word heard twice" when their
# midpoints agree within this tolerance. WHY 0.3 s: word-timestamp jitter
# between overlapping Parakeet windows is typically well under 200 ms;
# 0.3 s absorbs it without ever bridging two distinct short words apart.
DEDUPLICATION_TIME_TOLERANCE_S = 0.3


class StreamingChunkMerger:
    """Merges one speech segment's overlapping windows into one word list.

    One instance per (stream, speech segment). Feed windows with
    ``add_window`` (any order), read live text with ``merged_words``, and
    call ``flush`` when the segment closes to commit the tail.
    """

    def __init__(
        self,
        overlap_s: float = 0.8,
        dedup_tolerance_s: float = DEDUPLICATION_TIME_TOLERANCE_S,
    ) -> None:
        if overlap_s < 0:
            raise ValueError(f"overlap_s must be >= 0, got {overlap_s}")
        self._overlap_s = overlap_s
        self._dedup_tolerance_s = dedup_tolerance_s
        self._committed: list[WordToken] = []
        # Tentative: words in the trailing overlap of the newest processed
        # window — the NEXT window may still dispute them.
        self._tentative: list[WordToken] = []
        self._buffered: dict[int, TranscribedWindow] = {}
        self._next_index = 0
        self._processed_any = False

    def add_window(self, window: TranscribedWindow) -> None:
        """Accept one window; process it (and any unblocked successors) in order."""
        if window.index < self._next_index or window.index in self._buffered:
            # Fail closed: replaying an already-consumed index would merge
            # the same audio twice and double its words.
            raise ValueError(f"window index {window.index} was already received")
        self._buffered[window.index] = window
        while self._next_index in self._buffered:
            self._process_in_order(self._buffered.pop(self._next_index))
            self._next_index += 1

    def merged_words(self) -> list[WordToken]:
        """Snapshot of the merge so far: committed words + tentative tail."""
        return [*self._committed, *self._tentative]

    def flush(self) -> list[WordToken]:
        """Close the segment: drain buffered windows, commit the tail.

        Any windows still buffered (a gap in indices — e.g. a window's
        transcription failed) are processed in ascending order; the gap is
        simply absent audio, represented honestly as missing words.
        Resets state so the instance could serve another segment.
        """
        for index in sorted(self._buffered):
            self._process_in_order(self._buffered.pop(index))
        self._committed.extend(self._tentative)
        merged = self._committed
        self._committed = []
        self._tentative = []
        self._next_index = 0
        self._processed_any = False
        return merged

    def _process_in_order(self, window: TranscribedWindow) -> None:
        """Apply the midpoint-cut merge rule for the next window in order."""
        # Sort by midpoint: transcribers guarantee no intra-window order,
        # and the cut rule is defined over midpoints.
        incoming = sorted(window.words, key=lambda w: w.midpoint)

        if not self._processed_any:
            # First window of the segment owns everything it heard; its
            # trailing overlap stays tentative for the next window.
            self._processed_any = True
            self._split_commit_tentative(incoming, window)
            return

        cut = window.t_start + self._overlap_s / 2.0
        # Earlier window wins strictly BEFORE the cut: promote those
        # tentative words to committed; the rest are disputed territory
        # now owned by the (later) incoming window — drop them.
        self._committed.extend(w for w in self._tentative if w.midpoint < cut)
        self._tentative = []
        taken = [w for w in incoming if w.midpoint >= cut]

        # Boundary duplicate guard (jitter across the cut): drop the new
        # copy, keep the committed one. Casefold comparison only — this is
        # deduplication of the SAME token, never a rewrite (fidelity).
        if taken and self._committed:
            last, first = self._committed[-1], taken[0]
            same_text = last.text.casefold() == first.text.casefold()
            if same_text and abs(last.midpoint - first.midpoint) <= self._dedup_tolerance_s:
                taken = taken[1:]

        self._split_commit_tentative(taken, window)

    def _split_commit_tentative(self, words: list[WordToken], window: TranscribedWindow) -> None:
        """Commit words the next window cannot dispute; keep the rest tentative.

        The next window (if any) starts at ``window.t_end - overlap`` and
        its cut will sit at ``window.t_end - overlap/2`` — words at/after
        that point belong to it, so they stay tentative here.
        """
        trailing_cut = window.t_end - self._overlap_s / 2.0
        self._committed.extend(w for w in words if w.midpoint < trailing_cut)
        self._tentative = [w for w in words if w.midpoint >= trailing_cut]
