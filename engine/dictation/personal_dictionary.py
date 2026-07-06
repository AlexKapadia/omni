"""Personal spelling dictionary for dictation cleanup — %LOCALAPPDATA% file.

Purpose: load the user's personal term list (names, jargon, product words)
from ``%LOCALAPPDATA%/Omni/dictionary.txt`` and hand it to the cleanup
step as spelling-bias context. Format: one term per line; ``#`` starts a
comment line; blank lines ignored. The file is user-owned and optional.
Pipeline position: consumed by ``dictation_cleanup`` (both as prompt
context and as permitted vocabulary for the faithfulness guard).

Fail-open invariant (binding): dictation must NEVER fail because of this
file. A missing, unreadable, undecodable, or oversized dictionary degrades
to an empty term list, logged ONCE — the user's words always land.

Security invariants:
- Terms are untrusted input: length-capped, single-line by construction,
  control characters refused per-term (a bad line is skipped, not fatal).
- Read is size-capped so a huge/hostile file cannot balloon memory or the
  prompt (deny by default beyond the cap).
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Caps (deny by default beyond them): bytes read, terms kept, term length.
MAX_DICTIONARY_BYTES = 262_144  # 256 KiB — far beyond any honest term list
MAX_DICTIONARY_TERMS = 2_000
MAX_TERM_LENGTH = 64


def default_dictionary_path() -> Path | None:
    """``%LOCALAPPDATA%/Omni/dictionary.txt`` — None when the env var is
    absent (non-Windows CI): the caller fails open to an empty list."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data) / "Omni" / "dictionary.txt"


def parse_dictionary_lines(raw_text: str) -> tuple[str, ...]:
    """Parse dictionary file content into a capped, deduped term tuple.

    Rules: one term per line; lines starting with ``#`` (after leading
    whitespace) are comments; blank lines skipped; terms longer than
    :data:`MAX_TERM_LENGTH` or containing control characters are skipped
    (a bad line never poisons the rest — fail open per line); duplicates
    (case-sensitive) dedupe order-preserving; hard cap on total terms.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        term = line.strip()
        if not term or term.startswith("#"):
            continue
        if len(term) > MAX_TERM_LENGTH:
            continue  # cap per term: an absurd "term" is noise, not vocabulary
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in term):
            continue  # control chars never reach the prompt (injection surface)
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= MAX_DICTIONARY_TERMS:
            break  # hard cap: deny by default beyond it
    return tuple(terms)


class PersonalDictionary:
    """Cached, mtime-refreshed view of the user's dictionary file.

    ``terms()`` is cheap to call per-dictation: it re-reads only when the
    file's (mtime_ns, size) signature changes. Every failure mode returns
    the empty tuple and logs once (fail open — see module docstring).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else default_dictionary_path()
        self._cached_terms: tuple[str, ...] = ()
        self._cached_signature: tuple[int, int] | None = None
        self._failure_logged = False  # log-once latch for repeated failures

    def terms(self) -> tuple[str, ...]:
        """Current term list; () when absent/malformed (fail open)."""
        if self._path is None:
            self._log_failure_once("LOCALAPPDATA not set; personal dictionary disabled")
            return ()
        try:
            stat = self._path.stat()
        except OSError:
            # Missing file is the NORMAL state for most users — not an error.
            self._cached_terms = ()
            self._cached_signature = None
            return ()
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature == self._cached_signature:
            return self._cached_terms  # unchanged: serve the cache
        try:
            with self._path.open("rb") as handle:
                raw_bytes = handle.read(MAX_DICTIONARY_BYTES)  # size cap
            raw_text = raw_bytes.decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            # Fail open: a malformed dictionary must never block dictation.
            self._log_failure_once(f"personal dictionary unreadable ({exc}); ignoring it")
            self._cached_terms = ()
            self._cached_signature = signature  # don't re-log every call
            return ()
        self._cached_terms = parse_dictionary_lines(raw_text)
        self._cached_signature = signature
        self._failure_logged = False  # a good read re-arms the log-once latch
        return self._cached_terms

    def _log_failure_once(self, message: str) -> None:
        if not self._failure_logged:
            logger.warning("%s", message)
            self._failure_logged = True
