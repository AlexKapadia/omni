# Omni Redesign Brief v2 — "Daylight"

**Date:** 2026-07-08 · **Status:** ✅ APPROVED by user 2026-07-08 (evergreen teal accent · serif titles · Home + Record-CTA IA · onboarding keeps keys as an optional step, calendar/voice-enrollment deferred). Build via scoped subagents on `feature/ui-rehaul-v2`.
**Supersedes:** `design-brief.md` (v1 monochrome contract) and the visual sections of `docs/plans/2026-07-08-ui-rehaul-design-plan.md` once ratified. The UX/IA sections of that plan are absorbed and extended here.
**User mandate (2026-07-08):** full visual redesign + full UX rehaul. Pains confirmed: feature discoverability, navigation/structure, onboarding, density. Autonomous build after this brief is approved.

---

## 1. Diagnosis — why the app is still hard to use

The 2026-07-08 rehaul plan is ~70% executed (nav renames, v2 accent tokens, settings tiers, humanized settings copy all landed). What never landed is precisely what makes the app feel unintuitive:

1. **Onboarding front-loads config with no payoff.** Still 5 steps; blocks on a model download; ends at API keys + calendar. A new user never sees a transcript before finishing setup.
2. **Zero discoverability system.** No tooltips, coachmarks, tours, or shortcut help anywhere in the app. Live answers, vault suggestions, translation, captions overlay, and meeting board are invisible until the engine happens to emit something — or live behind an Advanced settings toggle.
3. **"Record" is a nav destination.** Recording is a *mode*, not a place; putting it beside Meetings/Ask makes the IA read as six equal rooms with no front door.
4. **Developer console leaks.** Ask shows `retrieval/synthesis/total ms` on every answer; Naomi shows a permanent latency table + dev tuning drawer; export speaks in `SRT/VTT/TXT/MD`; dictation rows print raw `entry.mode`; model names (`large-v3`, `whisper-1`) surface in Essentials.
5. **The design system renders in Segoe UI.** `fonts.css` was never shipped, so the specified Space Grotesk/Inter/JetBrains Mono fall back to system fonts on most installs. The craft users see is not the craft that was designed.
6. **Naomi is unexplained.** A first-timer meets a name, a pool of water, and a latency table.

## 2. North Star

> A user fluent in Notion or Granola trusts Omni in under 60 seconds, records something real within 3 minutes, and can name every major feature after one session — without a manual.

Brand stays **Calm · Private · Capable**. The register moves from *laboratory instrument* to *trusted studio*: warmer, more depth, more human — never AI-slop (no cream body washes, no purple gradients, no glass cards, no dark hacker chrome).

## 3. Competitive findings (fresh teardown, 2026-07-08)

| Reference | What we borrow (patterns, not pixels) |
| --- | --- |
| **Granola** | Invisible design: one action to record; user's own words visually distinct from AI text (black vs grey); app feels like "a second brain sitting quietly next to you"; zero config before value. |
| **Wispr Flow** | Works out of the box, no configuration; onboarding polish as a differentiator; auto-adapting output so the user never touches settings. |
| **Linear** | Reduce visual noise; hierarchy + density in navigation; speed *is* design; command palette as universal feature discovery. |
| **Apple Voice Memos** | Voice-notes list simplicity; a single, unmistakable record affordance. |
| **Onboarding research** | Aha under 5 min → ~40% higher 30-day retention; 30–40% of onboarding steps are removable; progressive disclosure over feature dumps. |

Sources: efficient.app & tldv.io & wondertools Granola reviews; efficient.app & spokenly Wispr Flow reviews; linear.app "How we redesigned the Linear UI"; appcues/userpilot/digitalapplied onboarding research (2026). Full links in `docs/design/research-2026-07-08-competitive-teardown.md`.

## 4. Visual language v2 — "Daylight"

The scene sentence still governs: *a knowledge worker at a desk in daylight, glancing between a call and a quiet sidebar.* The new language keeps chromatic restraint but abandons "total chromatic silence" and flat white-on-white in favor of **paper-on-desk layering**: a softly tinted canvas with pure-white raised surfaces, one signature accent, an ember for live state, and an editorial serif for titles.

### 4.1 Palette

| Token | Value | Role |
| --- | --- | --- |
| `--canvas` | `#FAFAF8` | App background — warm-tinted near-white paper (NOT cream; barely off-white) |
| `--surface` | `#FFFFFF` | Cards, panels, inputs — raised paper |
| `--surface-sunken` | `#F3F2EF` | Wells, code/transcript beds, track fills |
| `--border` | `#E9E8E4` | Hairlines |
| `--border-strong` | `#D6D4CE` | Control borders |
| `--ink` | `#1C1B18` | Primary text — warm soft black |
| `--ink-secondary` | `#6B6862` | Secondary text (AA on canvas & surface) |
| `--ink-tertiary` | `#8F8C84` | Meta/decoration only, never body text |
| `--accent` | `oklch(46% 0.09 175)` ≈ deep evergreen teal | Primary buttons, links, selection, focus ring. **≤8% of any screen.** |
| `--accent-strong` / `--accent-muted` / `--on-accent` | derived | hover/pressed · tint wash · white text (AA verified) |
| `--ember` | `oklch(58% 0.19 30)` warm coral-red | Live recording only — dot, ring, "Recording" pill |
| `--success/-text/-bg` `--warning*` `--error*` `--info*` | OKLCH triads | Semantic state, WCAG-verified |

Why evergreen, not ink-blue: every AI product is blue or purple; a deep teal-green reads private/calm/organic, sits naturally beside warm greys, and passes 4.5:1 with white text. The v2 ink-blue tokens are replaced wholesale (they shipped days ago; no migration debt).

Rules retained: **Accent Budget** (≤8%), **AA Secondary**, **One Shadow** (plus a new subtle `--shadow-raise 0 1px 2px rgba(28,27,24,0.06)` for resting cards — two-level elevation total), hue for state and accent only.

### 4.2 Typography (self-hosted — ships this time, Phase 1)

| Role | Face | Notes |
| --- | --- | --- |
| Display / titles | **Source Serif 4** 600 (self-hosted, OFL) | Editorial "trusted archive" warmth: screen titles, empty-state heroes, onboarding. Replaces Space Grotesk everywhere except the wordmark. |
| Wordmark | Space Grotesk 600 | Brand anchor only. |
| UI body | **Inter** 400/500/600 (self-hosted) | All UI. Sentence case everywhere; no uppercase eyebrows outside evidence tables. |
| Evidence | **JetBrains Mono** 400/500 (self-hosted) | Transcripts, citations, paths, ledger — nothing else. |

Scale: hero 44/1.1 · title 26/1.25 · section 19/1.35 · emphasis 15/1.5 · body 14/1.6 · transcript 13/1.6 · meta 12/1.5 (Inter, tabular-nums). Prose measure 65–75ch.

### 4.3 Shape, depth, motion

Cards 14px radius on `--surface` with `--border` + `--shadow-raise`; floating layers (palette, pill, popovers, toasts) keep the single `--shadow-float`. Controls 10px. No nested cards. Motion: 180–300ms ease-out; shared-layout nav indicator stays; breathing ring recolors to `--ember` while live; `prefers-reduced-motion` global freeze retained.

## 5. Information architecture v2

### 5.1 Shell

```
┌ rail ────────────┐
│ ● Record          │  ← primary action button (ember on hover/live), not a nav row
│──────────────────│
│ Home              │  ← NEW default screen
│ Meetings          │
│ Voice notes       │
│ Ask               │
│ Naomi             │
│──────────────────│
│ Settings          │
│ "Your data stays  │
│  on this device"  │
└──────────────────┘
```

- **Record becomes a button, not a place.** Pressing it starts capture and opens the Live view (which exists only while a session is active or unfinalized). `SectionId` keeps `live` internally; the rail row is replaced by the CTA.
- **Home (new, default):** the front door that answers "what can this app do for me right now": greeting + Record CTA; upcoming calendar meetings (or a quiet connect prompt); drop-a-file import target; Ask input inline; recent meetings & voice notes; and up to three dismissible **discover cards** (captions overlay, translation, dictation hotkey, Naomi) that deep-link with a coachmark. Library remains one click away; Home replaces it as landing.
- **Command palette (Ctrl+K):** every screen, action, and feature by name ("Start recording", "Import a file", "Open live captions", "Pause all cloud AI"). Doubles as the discoverability index. `Ctrl+/` opens shortcut help.

### 5.2 Discoverability system (new, lightweight)

One `useCoachmark(id)` primitive: anchored, dismissible, shown once, stored locally, max one visible at a time, never blocks input. Budget: 3 on first Home visit, 2 on first Live session, 1 each for Ask/Naomi/Voice notes. Plus first-class `Tooltip` on every icon-only control (contract: **no icon-only control without a tooltip**), educational empty states everywhere, and contextual feature prompts replacing onboarding config (see §7).

### 5.3 Live view — visible, labeled capabilities

Header: editable title · **Recording ● 12:34** ember pill · Stop. Below the header, a **capability strip** of labeled, tooltipped toggle chips — `Notes · Summary · Answers · Translate · Captions · Board` — each toggling its panel; Translate opens an inline language picker on first use (no trip to Advanced); Captions launches the overlay (no longer buried in Automation); Board renders live (today it only exists in the library detail). Transcript dominant in the center, "You / Everyone else" streams; ink vs secondary distinction (Granola pattern). After Stop: a single clear **"Create enhanced note"** primary action with plain-language explanation, then deep-link to the finished note in Meetings.

### 5.4 Screen-level changes

| Screen | Change |
| --- | --- |
| **Meetings** | List stays home for history: day-grouped rows (serif title, relative date, duration chip). Detail tabs Summary · Transcript · Chat · **Export** with human export labels: "PDF document", "Word document", "Markdown", "Subtitles (SRT)", "Subtitles (VTT)", "Plain text" — icon + label buttons. |
| **Ask** | Scope chips **All meetings · This meeting · Voice notes**. Latency line removed from answers (debug toggle in Diagnostics only). Empty state teaches citations. |
| **Voice notes** | Mode chips humanized (Note / Command / Pasted), hotkey hero kept, row meta in Inter. |
| **Naomi** | First-run explainer card: "Naomi listens, finds answers in your notes, and *prepares* actions — nothing runs until you approve it." Latency table + dev tuning drawer move behind the existing debug opt-in. Approval-card eyebrows → sentence case. |
| **Settings** | Tiers stay. Transcription model/URL fields collapse behind "Show advanced options" within the card. "Echo cancellation (AEC)" → "Echo reduction". Remaining uppercase eyebrows (approval cards, vault suggestions, transcript tag) → sentence case; ledger table header may stay mono-caps (evidence register). |
| **Status footer** | Keeps real-time speed **per standing user preference** (overrides the old hide-latency plan): redesigned as `Ready · 367 ms` with the stt engine/device string moved to a hover/Diagnostics detail. Copy stays humanized. |
| **Pill / captions** | Already humanized; recolor to Daylight tokens; pill lock state gets its padlock tooltip. |

## 6. Copy system

`apps/ui/copy/glossary.json` becomes the **runtime** source of truth: typed accessor (`copy.nav.home`…), all renamed strings live there, tests import from it so renames propagate. Error copy formula everywhere: *what happened / why / one fix*. Voice: direct, human, no architecture nouns in primary UI.

## 7. Onboarding v2 — three steps to a real transcript

Target: **aha ≤3 minutes**, zero required config.

| Step | Content |
| --- | --- |
| **1 · Welcome** | Serif hero + the three privacy truths, one CTA "Get started". Background: default vault (`~/Documents/Omni`) is created and the Fast model download starts silently. |
| **2 · Your notes live here** | Shows the default folder, one-click "Use this folder" (or change). Explains vault in one sentence. |
| **3 · Try it — 20-second test** | Mic-only test recording with the live transcript appearing as they speak (model progress inline if still downloading). Payoff screen: their words, labeled streams, "This is what every meeting becomes." |
| **4 · Connect AI (optional)** | API keys step retained per user decision — clearly optional, "Skip for now" prominent; explains what keys unlock (enhanced notes, Ask synthesis) and that everything local works without them. → Home with its 3 coachmarks. |

Deferred to context: voice enrollment (offered after first real meeting finalize), calendar (quiet Home prompt), captions/translation (Live capability strip). Skippable at every step; never re-shown.

## 8. Build plan (after approval) — branch `feature/ui-rehaul-v2`

| Phase | Scope | Gate |
| --- | --- | --- |
| **P1 Foundation** | Daylight tokens.css rewrite · fonts.css + self-hosted woff2 · primitives (Button/Tooltip/Coachmark/chip) · glossary as runtime module | vitest green, tokens-only colors |
| **P2 Shell & Home** | Rail with Record CTA · Home screen · command palette · shortcut help · footer redesign | tests updated, all states real |
| **P3 Live & screens** | Capability strip + panels · finalize flow · Meetings/Ask/Voice notes/Naomi/Settings changes per §5.4 | tests updated |
| **P4 Onboarding** | 3-step flow + background download + test recording + contextual prompts | wizard tests rewritten |
| **P5 Verify & ship** | Full vitest suite · live E2E drive of every control · screenshot→critique→fix loop (separate evaluator) · WCAG 2.2 AA pass · evidence capture | UI Definition-of-Done |

Every phase commits + pushes on green. String-coupled test files (list in audit §11) are updated in lockstep with each rename — tests import from the glossary where possible.

## 9. Success criteria

Time to first transcript < 3 min · every major feature reachable AND named from Home or the capability strip or Ctrl+K · zero engineer jargon in default chrome (footer speed excepted by user preference) · zero icon-only controls without tooltips · WCAG 2.2 AA · all existing behavior preserved (no feature removals — this is comprehension, not amputation).

## 10. Open decisions for approval

1. **Accent = deep evergreen teal** (replacing the just-shipped ink-blue) — or keep ink-blue with the rest of Daylight?
2. **Serif display (Source Serif 4)** for titles/heroes — or stay all-sans (Inter Display)?
3. **Home screen + Record-as-button IA** — the biggest structural change.
4. Onboarding v2 with deferred keys/calendar — confirm nothing must remain mandatory.
