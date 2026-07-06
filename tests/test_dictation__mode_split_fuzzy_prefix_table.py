"""Mode splitter decision table: fuzzy wake-word prefixes, unicode, empties.

The split decides whether a released dictation becomes a note (safe) or a
command (privileged path -> recorded intent), so the boundary cases are
security cases: "omnibus" must NEVER be a command, and the command body
must be an exact verbatim suffix (fidelity mandate).
"""

import pytest

from engine.dictation.dictation_mode_splitter import (
    DictationMode,
    ModeSplit,
    split_dictation_mode,
)

# (input text, expected mode, expected command body)
DECISION_TABLE: list[tuple[str, DictationMode, str]] = [
    # --- canonical command forms ---
    ("Omni, schedule lunch with Tom", DictationMode.COMMAND, "schedule lunch with Tom"),
    ("omni, schedule lunch", DictationMode.COMMAND, "schedule lunch"),
    ("OMNI, SCHEDULE LUNCH", DictationMode.COMMAND, "SCHEDULE LUNCH"),
    ("Omni schedule lunch", DictationMode.COMMAND, "schedule lunch"),  # STT drops the comma
    ("Omni. schedule lunch", DictationMode.COMMAND, "schedule lunch"),
    ("Omni: draft an email to dana", DictationMode.COMMAND, "draft an email to dana"),
    ("Omni; remember this", DictationMode.COMMAND, "remember this"),
    ("Omni — create an event", DictationMode.COMMAND, "create an event"),
    ("Omni- create an event", DictationMode.COMMAND, "create an event"),
    ("  Omni, indented start", DictationMode.COMMAND, "indented start"),
    ('"Omni, quoted wake"', DictationMode.COMMAND, 'quoted wake"'),
    ("...Omni, ellipsis lead-in", DictationMode.COMMAND, "ellipsis lead-in"),
    ("Omni,schedule lunch", DictationMode.COMMAND, "schedule lunch"),  # no space after comma
    # --- unicode / accent fuzz (STT sometimes emits diacritics) ---
    ("Ómni, schedule lunch", DictationMode.COMMAND, "schedule lunch"),
    ("ÖMNI, schedule lunch", DictationMode.COMMAND, "schedule lunch"),
    # --- wake word alone: command with empty body (recorded as unknown) ---
    ("Omni", DictationMode.COMMAND, ""),
    ("Omni,", DictationMode.COMMAND, ""),
    ("omni   ", DictationMode.COMMAND, ""),
    # --- NOT commands: the wake word must be the WHOLE first word ---
    ("omnibus schedules are confusing", DictationMode.NOTE, ""),
    ("Omniscient narrators are fun", DictationMode.NOTE, ""),
    ("omni2 is a version number", DictationMode.NOTE, ""),
    ("omni-channel strategy thoughts", DictationMode.NOTE, ""),  # hyphenated word
    ("Omni-first design notes", DictationMode.NOTE, ""),
    ("The omni channel strategy", DictationMode.NOTE, ""),  # wake word not FIRST
    ("remember to buy milk", DictationMode.NOTE, ""),
    ("schedule lunch with Omni", DictationMode.NOTE, ""),
    # --- degenerate inputs ---
    ("", DictationMode.NOTE, ""),
    ("   ", DictationMode.NOTE, ""),
    (",,,", DictationMode.NOTE, ""),
    ("\n\t", DictationMode.NOTE, ""),
    ("😀 omni, emoji first word is not the wake word", DictationMode.NOTE, ""),
]


@pytest.mark.parametrize(("text", "mode", "body"), DECISION_TABLE)
def test_mode_split_decision_table(text: str, mode: DictationMode, body: str) -> None:
    assert split_dictation_mode(text) == ModeSplit(mode=mode, command_body=body)


def test_command_body_is_exact_suffix_of_input() -> None:
    """Fidelity: the body is a contiguous verbatim SUFFIX — front-trimmed
    only, never rewritten. (The full property sweep lives in
    test_dictation__verbatim_fidelity_property.py.)"""
    for text, mode, _body in DECISION_TABLE:
        split = split_dictation_mode(text)
        if mode is DictationMode.COMMAND:
            assert text.endswith(split.command_body)


def test_note_mode_never_yields_a_body() -> None:
    """A note carries no command body by construction — the caller keeps
    the ORIGINAL text; an accidental body would imply a rewrite."""
    for text, mode, _body in DECISION_TABLE:
        if mode is DictationMode.NOTE:
            assert split_dictation_mode(text).command_body == ""
