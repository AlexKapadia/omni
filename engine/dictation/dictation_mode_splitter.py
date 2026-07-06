"""Mode split for released dictation: "Omni,"-prefixed = COMMAND, else NOTE.

Purpose: the single, deterministic rule deciding whether a finished
dictation is a note (the default) or a command addressed to Omni. The rule
is a WAKE-WORD-FIRST-WORD check, deliberately narrow: only a leading
"omni" *word* (case-insensitive, accent-insensitive — STT sometimes emits
diacritics) followed by a word boundary triggers command mode. "omnibus",
"omniscient" etc. are notes — the wake word must be the whole first word.
Pipeline position: called by ``dictation_finalization`` on the verbatim
released text; mirrored (for the live chip flip only) by the pill UI's
``omni-command-prefix-detector.ts`` — THIS module is authoritative.

Fidelity invariant (binding): the command body is an exact contiguous
suffix of the input text — characters are only ever *removed from the
front* (wake word + separators), never rewritten. NOTE mode leaves the
text untouched entirely (the caller keeps the original string).
"""

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

# The wake word, compared against the FOLDED first word (see _fold_word).
WAKE_WORD = "omni"

# Characters ignored BEFORE the first word: whitespace plus punctuation STT
# or the user may front-load ("...Omni", quotes, dashes). Letters/digits stop
# the trim — a word is never eaten.
_LEADING_TRIM = " \t\r\n\"'“”‘’.,:;!?…—–-()[]{}"  # noqa: RUF001 — curly quotes/dashes are deliberate STT variants

# Separators consumed BETWEEN the wake word and the command body: the "," in
# "Omni," plus the variants STT actually produces (period, colon, dashes...).
_SEPARATOR_TRIM = " \t\r\n,.:;!?…—–-"  # noqa: RUF001 — en/em dashes are deliberate STT variants

# Hyphen characters that glue words together: "omni-channel" is ONE word,
# not a wake word — a hyphen directly followed by a letter continues the word.
_WORD_HYPHENS = "-–—"  # noqa: RUF001 — en dash is a deliberate hyphen variant


class DictationMode(StrEnum):
    """The two things a released dictation can be. Values are pinned by the
    ``dictation.final`` event payload — do not rename."""

    NOTE = "note"
    COMMAND = "command"


@dataclass(frozen=True)
class ModeSplit:
    """The split decision: mode plus (for COMMAND) the verbatim body."""

    mode: DictationMode
    # Exact suffix of the input after the wake word + separators; always ""
    # for NOTE mode (the caller uses the original text — fidelity mandate).
    command_body: str


def _fold_word(word: str) -> str:
    """Casefold + strip combining accents, for wake-word comparison ONLY.

    NFKD decomposition then dropping combining marks makes "Ómni"/"omni"
    equal without ever altering the text that flows onward — folding is a
    comparison key, not a rewrite.
    """
    decomposed = unicodedata.normalize("NFKD", word)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def split_dictation_mode(text: str) -> ModeSplit:
    """Decide NOTE vs COMMAND for one released, verbatim dictation.

    Inputs: the verbatim transcript (any unicode, may be empty).
    Output: a :class:`ModeSplit`. Deny-by-default posture: anything that is
    not an unambiguous leading wake WORD is a note — notes are safe (no
    action), commands are the privileged path.
    """
    stripped = text.lstrip(_LEADING_TRIM)
    # The first word = the maximal leading alphanumeric run. Including
    # digits in the run means "omni2" is one (non-matching) word, not a
    # wake word with a "2" body.
    end = 0
    while end < len(stripped) and stripped[end].isalnum():
        end += 1
    first_word = stripped[:end]
    # Hyphenated continuation ("omni-channel", "Omni-first"): still one word,
    # so NOT the wake word — misrouting it to command mode would divert the
    # user's words away from the vault (fail open for words).
    hyphen_continues_word = (
        end + 1 < len(stripped)
        and stripped[end] in _WORD_HYPHENS
        and stripped[end + 1].isalnum()
    )
    if first_word and not hyphen_continues_word and _fold_word(first_word) == WAKE_WORD:
        # Command body: exact suffix after the wake word, minus separator
        # punctuation. Only front-trimming — never a rewrite (fidelity).
        body = stripped[end:].lstrip(_SEPARATOR_TRIM)
        return ModeSplit(mode=DictationMode.COMMAND, command_body=body)
    return ModeSplit(mode=DictationMode.NOTE, command_body="")
