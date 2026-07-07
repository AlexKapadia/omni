<!--
Thanks for contributing to Omni. Fill this in honestly — a reviewer checks the
real artifacts (the diff, the CI run, the tests), not the ticked boxes. An
unchecked box with a note is far better than a checked one that isn't true.
-->

## What this changes

<!-- One or two sentences. What does this PR do, and why? -->

Closes #<!-- issue number, if any -->

## Type of change

- [ ] New ability (agent tool) — a new thing Naomi / the approval system can do
- [ ] Bug fix
- [ ] Feature / improvement (non-ability)
- [ ] Docs / infrastructure only

## The gate is green

Ran locally before pushing (CI runs the same on Linux):

- [ ] `uv run ruff check .` — clean
- [ ] `uv run mypy` — clean
- [ ] `uv run pytest` — all green
- [ ] `pnpm run typecheck` (in `apps/ui/`) — clean *(only if UI changed)*
- [ ] `pnpm run test` (in `apps/ui/`) — green *(only if UI changed)*

## Quality bar

- [ ] Every changed source file is **≤ 300 lines** with a self-documenting name
- [ ] Added **adversarial tests with teeth** — boundary-exact, would fail if the
      code were wrong — not happy-path or tautological
- [ ] Coverage still clears the gate (line ≥ 90% / branch ≥ 85% on engine code)
- [ ] No dead code left behind (superseded code deleted in the same change)
- [ ] Docs updated if behavior changed

## Security invariants upheld

<!-- If your change touches actions, egress, keys, or the vault, confirm these.
     If it can't honestly tick a box, say so here and let's talk. -->

- [ ] **Approval-before-execute** — nothing new can run without an approved card
- [ ] **Draft-only** — nothing new sends on the user's behalf
- [ ] **Local-first / zero telemetry** — no new data leaves the machine except an
      explicit, minimal, user-configured model call; `data_sent_off_machine` is
      accurate
- [ ] **Keys** stay DPAPI-only and engine-only (no keys in files, logs, env, or
      the UI process)
- [ ] No security control (SQL trigger, `CHECK`, guard, or test) was weakened to
      pass

## For a new ability, also confirm

<!-- Delete this section if not adding a tool. -->

- [ ] New `card_type` added via a **new migration** that rebuilds the CHECK
      constraint (did not edit `0007`/`0008`); triggers copied verbatim
- [ ] Tool registered in `default_tool_registry.py`; mapper branch added
- [ ] `dry_run` preview pinned by an exact-match test
- [ ] The "exactly N card types" count guard updated (it should have gone red)
- [ ] If voice-invokable: intent type, dictation payload branch, and Naomi
      confirmation line all wired

## Notes for the reviewer

<!-- Anything worth flagging: trade-offs, follow-ups, things you're unsure about. -->
