# Product

## Register

product

## Users

Knowledge workers and professionals who spend significant time in meetings and calls — often with headphones, often handling sensitive topics. Many already use Obsidian (or similar markdown vaults) as their personal knowledge base. They are privacy-conscious: they refuse bot-in-call recorders and cloud-first note tools that upload by default. Context when using Omni: at a desk during a video call, between meetings reviewing notes, or anywhere via global voice dictation.

Secondary users: developers and power users who want BYOK AI routing, audit logs, and advanced controls — but the primary experience must not require understanding engine architecture.

## Product Purpose

Omni is local-first meeting and voice intelligence: bot-free capture, on-device transcription, enhanced notes woven around the user's own words, vault-native search with citations, and approval-carded actions (calendar, contacts, Gmail drafts — never send). Global dictation and Naomi voice mode extend the same engine between meetings.

Success looks like: a user fluent in Notion or Granola trusts Omni in under 60 seconds, completes a first meeting with useful enhanced notes, and never wonders whether their audio or transcripts left the machine without consent.

**Tagline (consumer-facing):** Meeting notes that stay yours.

**Product name:** Omni (keep consistently in UI; avoid "Omni+" in user-facing surfaces).

## Brand Personality

**Three words:** Calm · Private · Capable

Voice is direct and human — never engineer jargon in primary UI ("AI router", "STT", "kill switch"). Confidence comes from restraint: white space, honest states, real citations. Naomi is the one allowed character name; she prepares actions, never executes without approval.

Emotional goal: *trusted companion at the desk*, not a flashy AI dashboard or developer console.

## Anti-references

- Generic "AI slop" UI: cream/sand/beige warm-neutral body backgrounds, gradient cards, nested card grids, purple-on-white chatbot aesthetic
- Developer-console aesthetic: monospace uppercase labels on every nav item, latency numbers in the default footer, model names in primary settings
- Bot-in-call meeting tools (Grain, Otter-style joiners) — Omni never joins a call
- Dark-mode-by-default "hacker tool" chrome — light, daylight desk scene is the default
- Decorative motion, bounce easing, gradient text, side-stripe accent borders
- Static mockups: every visible control must wire to real behavior and real-shaped data

## Design Principles

1. **Privacy is the product** — local-first, zero telemetry; audio is kept on-device as MP3 with the transcript by default and never uploaded (opt out to discard); copy and UI must reinforce this without fear-mongering.
2. **Progressive disclosure** — Essentials for 80% of users; router matrix, ledger, and diagnostics live under Advanced.
3. **Human language over architecture** — user-facing strings describe outcomes ("Pause all cloud AI"), not implementation ("kill switch").
4. **Evidence layer stays mono** — transcripts and timestamps may use monospace; general UI uses Inter sentence case, not uppercase eyebrows.
5. **One primary action per screen** — bold primary, ghost everything else; no nested cards.
6. **Approval before execute** — Naomi and extraction propose; the user approves. Never auto-run sensitive actions.

## Accessibility & Inclusion

- Target **WCAG 2.2 AA** for all shipped UI (automated checks + manual keyboard/focus review).
- Secondary text uses `--ink-secondary` (#6E6E6E), never `--grey-400`, for AA contrast on canvas and surface.
- Honor `prefers-reduced-motion`: freeze loops, keep end states (already in tokens.css).
- Do not rely on color alone for state — pair live indicator, weight, and labels.
- Future accent colors (UI rehaul) must meet contrast floors; semantic success/warning/error need text-safe pairs.

## Strategic references

- Product feature catalog: `docs/features.md`
- UI rehaul proposal (copy, IA, visual evolution): `docs/plans/2026-07-08-ui-rehaul-design-plan.md`
- Engineering invariants: `CLAUDE.md`, `docs/threat-model.md`
