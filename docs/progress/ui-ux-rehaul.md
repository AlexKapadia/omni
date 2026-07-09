# Progress Tracker — Full UI/UX Rehaul (v2 redesign)

**North Star:** Omni becomes a best-in-class app: every feature instantly understandable, navigation obvious, onboarding reaches the aha moment fast, with a brand-new visual language (full redesign — monochrome contract v1 is superseded once brief v2 is ratified).

**User decisions (2026-07-08):** full visual redesign + UX rehaul; all four pains confirmed (discoverability, navigation, onboarding, density); autonomous AFTER brief approval; references chosen by research.

## Checklist
- [x] G1a Audit current UI/UX — DONE (Explore agent report reconciled; rehaul plan ~70% landed; gaps: onboarding, discoverability, fonts, debug leaks)
- [x] G1b Competitive teardown — DONE (docs/design/research-2026-07-08-competitive-teardown.md)
- [x] G1c Redesign brief v2 WRITTEN (docs/design/redesign-brief-v2.md) → AWAITING USER APPROVAL
- [ ] G2a Tokens + primitives (branch: feature/ui-rehaul-v2)
- [ ] G2b IA + screens rebuild
- [ ] G2c Onboarding rebuild
- [ ] G3 Verify: vitest green, live E2E, visual review loop, a11y
- [ ] Close-out: evidence, commit+push, tracker COMPLETE

## Resume here
Brief v2 presented to user 2026-07-08. If approved: create branch feature/ui-rehaul-v2, start P1 (tokens+fonts+primitives+glossary runtime). If awaiting answer: do nothing destructive. Open decisions: accent (evergreen vs ink-blue), serif display, Home+Record-CTA IA, deferred onboarding config.

## Agent ledger
- Explore agent "Audit Omni UI state" — returned compact report, reconciled 2026-07-08. Key facts: v2 accent tokens exist (tokens.css:99-157); fonts.css absent; onboarding still 5-step; no tooltips/coachmarks anywhere; footer latency is a STANDING USER PREFERENCE (status-footer.tsx:4-7) — keep visible.

## Decisions & evidence
- Existing v1 design contract: docs/design/design-brief.md (monochrome). Superseded by v2 upon approval.
- Pre-existing uncommitted changes in tree (.coveragerc, .cursor/*) — NOT mine, do not touch/commit/revert (§7.6).

## Gate state
G1 in progress. main last commit b33899a.
