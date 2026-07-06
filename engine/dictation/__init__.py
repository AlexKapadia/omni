"""Dictation (M5): global push-to-talk mic-only STT -> note or command intent.

Pipeline: the Tauri shell holds F9 -> ``dictation.begin`` -> mic-only STT
session (own VAD/Parakeet instances composing ``engine.stt`` building
blocks) -> release -> ``dictation.end`` -> verbatim text -> mode split
("Omni,"-prefixed = COMMAND, else NOTE) -> command intents are parsed and
RECORDED (never executed); notes land in the vault Inbox and the index.

Binding invariants:
- Fidelity: the dictated text is ground truth — never rewritten anywhere.
- Approval-before-execute: this package has NO execution path at all;
  intents are appended to ``dictation_intents`` for M4 approval cards.
- Fail open for the user's words (router down -> timestamp-titled note is
  still saved), fail closed for actions (unknown/unparsable -> recorded
  only, deny by default).
"""
