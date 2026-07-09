# Threat model (STRIDE)

Living overview of trust boundaries for Omni. Report vulnerabilities per [SECURITY.md](../SECURITY.md) — do not file public issues for exploitable findings.

**Assets:** meeting audio/transcripts, vault markdown, API keys (DPAPI), approval cards, audit log, user calendar/contacts (via Google/Microsoft).

**Trust boundaries:**

1. **Internet ↔ engine** — model provider APIs only; kill-switch can deny all egress.
2. **UI ↔ engine** — WebSocket on `127.0.0.1`; pinned protocol; malformed frames dropped.
3. **Engine ↔ OS** — capture devices, vault filesystem, DPAPI, optional Google/Microsoft OAuth.
4. **Untrusted content ↔ models** — transcripts, vault excerpts, meeting notes treated as data not instructions.

## STRIDE summary

| Threat | Examples | Mitigations |
| --- | --- | --- |
| **Spoofing** | Fake engine WS endpoint | Loopback bind only; UI connects to configured localhost port |
| **Tampering** | Rewriting audit rows or approved card payloads | Append-only audit; SQL triggers on card status/payload immutability |
| **Repudiation** | Denying an executed action | Audit log + router cost ledger per external call |
| **Information disclosure** | Keys in logs, vault exfil via tool | DPAPI engine-only; minimum excerpt per model call; `data_sent_off_machine` on tools |
| **Denial of service** | Engine crash loops | Sidecar supervisor with backoff; capture fails closed without STT stack |
| **Elevation of privilege** | Unapproved calendar send / Gmail send | Approval-before-execute; Gmail draft-only; instant-execute whitelist explicit |

## Key invariants (enforced in code)

- **Local-first** — no telemetry; audio not uploaded; transcripts stay on disk unless user-configured model calls.
- **Fail closed** — missing key, ambiguous permission, or kill-switch → refuse egress, not partial send.
- **Never edit user prose** — vault writes append or use managed regions; collision suffixing on new notes.
- **Draft-only outbound** — no tool sends email or posts on behalf of user without a separate user action outside Omni.
- **Untrusted input** — dictation and document text passed as structured fields, not concatenated into system prompts for intent parsing.

## Out of scope

- Attacker with full interactive access to the user's Windows account (DPAPI keys are user-scoped).
- Compromise of third-party providers (Groq, Google, etc.) — user chose to configure those keys.
- Physical access scenarios beyond standard OS account security.

## When this document changes

Update this file when adding:

- A new external integration or egress path
- A new agent tool or auto-execute path
- A new secret storage location
- A new network listener or IPC surface

Pair schema changes with migrations and adversarial tests. See [CONTRIBUTING.md](../CONTRIBUTING.md) non-negotiables.
