# Security Policy

Omni handles some of the most private data a person has — the audio and
transcripts of their meetings, their notes, their contacts, and their API keys.
The entire product is a promise that this data stays on their machine and under
their control. We take that promise, and any report that helps us keep it,
seriously.

## Reporting a vulnerability

**Please do not open a public GitHub issue for a security vulnerability.**
Disclosing it publicly before there's a fix puts users at risk.

Instead, report it privately:

- **Email:** **alexanderkapadia2@gmail.com** — put `SECURITY` in the subject line.
- If GitHub [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  is enabled on the repository, you may use that instead.

Please include, as far as you can:

- A description of the issue and the invariant it breaks.
- Steps to reproduce (a minimal proof-of-concept is ideal).
- The versions / commit affected, and your assessment of the impact.

You'll get an acknowledgement as soon as we can, and we'll keep you updated as we
work on a fix. We're a small project run largely by one maintainer, so please be
patient — but we will not ignore a genuine report. If you'd like credit for the
find, tell us and we'll be glad to name you.

**Please do not** run automated scanners against infrastructure you don't own,
test against anyone else's data, or access, modify, or destroy data that isn't
yours while investigating. Good-faith research that respects users' privacy is
always welcome.

## Scope

Omni is a local-first desktop app: a Tauri 2 shell and a Python engine sidecar
that runs on `127.0.0.1` only, with no backend and no accounts. Reports that are
in scope include, for example:

- Anything that causes data to **leave the machine** outside the model calls the
  user explicitly configured — telemetry, exfiltration, or an over-broad request
  that sends more than a task needs.
- Anything that lets an action **execute without the user's approval**, or that
  bypasses the approval-card status machine.
- Anything that turns the **draft-only** Gmail capability into a send.
- **Key exposure** — an API key written to disk in plaintext, logged, leaked to
  the UI process, or otherwise recoverable outside DPAPI.
- **Prompt-injection** paths where untrusted transcript or document content
  reaches a model as instructions rather than as data, or drives an unapproved
  action.
- **Local privilege / integrity** issues — tampering with the append-only audit
  log, the migration bookkeeping, or the vault's managed regions; or a path that
  overwrites user-authored content.
- Standard web/app classes in the WebSocket protocol or the Tauri seams that
  could be reached by a local attacker.

Generally **out of scope**: issues that require an attacker to already have full
control of the user's OS account (Omni's DPAPI keys are, by design, only as safe
as the Windows user session); vulnerabilities in third-party AI providers you
send data to by choice; and reports that amount to "the app makes network calls
to the providers the user configured" — that's the documented, opt-in behavior.
See also [docs/threat-model.md](docs/threat-model.md) for the STRIDE overview.

## The invariants we defend

These are the security properties Omni enforces in code — SQL triggers, pydantic
models, DPAPI, and source-scanning tests — not by convention. A report that
breaks one of these is exactly what we want to hear about:

- **Local-first.** Transcripts, embeddings, notes, and keys never leave the
  machine except as the minimum excerpt inside a model call the user configured.
- **Audio is never uploaded.** Recordings are kept on-device as MP3 alongside
  the transcript by default; the user can opt out (discard after transcription)
  in Privacy settings. Kept or not, audio never leaves the machine.
- **Zero telemetry.** No phone-home of any kind.
- **Approval-before-execute.** No calendar event, contact upsert, vault write,
  or draft runs without an approved card. Cards are born `pending` and the legal
  status transitions are enforced by database triggers.
- **Draft-only.** Omni drafts mail; it has no send capability anywhere in the
  codebase, and tests scan the sources to keep it that way.
- **Keys via Windows DPAPI**, held only by the engine, never plaintext on disk,
  never logged, never in the UI process.
- **Untrusted input everywhere.** All transcript and document content is treated
  as untrusted at every model boundary (prompt-injection defence).
- **Append-only audit log** of every executed action and external model call:
  what, when, which provider, and exactly what data left the machine.
- **Kill-switch.** One flag halts all external calls; local capture,
  transcription, and vault features keep working. It fails closed on egress,
  never on the user's own data.

## No telemetry — by design

Omni does not collect analytics, usage data, crash reports, or any other
phone-home signal, and it never will. This means we won't learn about a bug from
a dashboard — we learn about it from you. That's a deliberate trade, and it's why
clear, reproducible reports matter so much here. Thank you for making them.
