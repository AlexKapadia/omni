"""Dictation (M5): global push-to-talk mic-only STT -> note or command intent.

Pipeline: the Tauri shell holds F9 -> ``dictation.begin`` -> mic-only STT
session (own VAD/Parakeet instances composing ``engine.stt`` building
blocks) -> release -> ``dictation.end`` -> verbatim text -> mode split
("Omni,"-prefixed = COMMAND, else NOTE, or the UI-requested INJECT) ->
command intents are parsed and RECORDED (never executed); notes land in
the vault Inbox and the index; inject returns cleaned text for the shell
to paste into the app focused at keydown.

The Wispr-Flow-beating layer (same package): ``dictation_cleanup`` (task
``dictation_cleanup``, faithfulness-guarded: fillers out, self-corrections
resolved, meaning never changed, raw ALWAYS retained) and
``personal_dictionary`` (%LOCALAPPDATA%/Omni/dictionary.txt, fail-open
spelling bias).

Binding invariants:
- Fidelity: the RAW dictated text is ground truth — never rewritten; the
  cleaned text is a separate, guard-checked artifact that degrades to raw.
- Approval-before-execute: this package has NO execution path at all;
  intents are appended to ``dictation_intents`` for M4 approval cards.
- Fail open for the user's words (router down -> timestamp-titled note is
  still saved), fail closed for actions (unknown/unparsable -> recorded
  only, deny by default).
"""
