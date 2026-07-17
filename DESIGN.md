---
name: Omni
description: Local-first meeting and voice intelligence — calm monochrome product UI
colors:
  canvas: "#FFFFFF"
  ink: "#0A0A0A"
  ink-secondary: "#6E6E6E"
  surface: "#F7F7F7"
  border: "#EDEDED"
  control-border: "#D4D4D4"
  tertiary-emphasis: "#525252"
  decoration-muted: "#A3A3A3"
typography:
  display:
    fontFamily: "'Space Grotesk', 'Segoe UI', system-ui, sans-serif"
    fontSize: "56px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.04em"
  title:
    fontFamily: "'Space Grotesk', 'Segoe UI', system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  emphasis:
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 500
    lineHeight: 1.5
  transcript:
    fontFamily: "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0.08em"
rounded:
  chip: "4px"
  control: "8px"
  card: "12px"
  pill: "999px"
  keycap: "6px"
  bubble: "10px"
spacing:
  hairline: "4px"
  control-inner: "8px"
  control-padding: "12px"
  row-gap: "16px"
  card-padding: "24px"
  section-gap: "32px"
  page-margin: "48px"
  canvas-breathing: "64px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
  button-secondary:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
  card-surface:
    backgroundColor: "{colors.canvas}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-padding}"
  input-field:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "12px"
---

# Design System: Omni

## Overview

**Creative North Star: "The Trusted Archive"**

Omni's interface should feel like a quiet, well-lit archive: evidence on the page (transcripts, citations, ledger entries), calm white canvas, and hierarchy expressed through weight and spacing — not hue. The current shipped system (v1.0) enforces **total chromatic silence**: black, grey, and white only; state is weight, scale, motion, and depth.

This document captures the **committed tokens** in `apps/ui/src/styles/tokens.css` and `docs/design/design-brief.md`. The [UI rehaul plan](docs/plans/2026-07-08-ui-rehaul-design-plan.md) proposes a **restrained evolution**: one accent ≤8% of surface, semantic state colors, and narrower mono usage — implement that as a deliberate version bump, not drift.

**Key characteristics:**

- Monochrome palette with WCAG-safe secondary text (`--ink-secondary`)
- Space Grotesk for display/wordmark; Inter for UI body; JetBrains Mono for transcript evidence and (today) section labels
- Single float shadow (`--shadow-float`); tonal layering otherwise
- 180–300ms ease-out motion; breathing ring is the only permanent loop during live capture
- Token-driven: components consume CSS variables only — no raw hex in components

## Colors

Strict monochrome today. Decoration-only greys must not be used for readable text.

### Primary

- **Ink** (`#0A0A0A` / `--ink`): Primary text, primary buttons, "Me" stream, active borders, focus rings.

### Neutral

- **Canvas** (`#FFFFFF` / `--canvas`): App background.
- **Surface** (`#F7F7F7` / `--grey-50`): Hover fills, active nav, permitted vertical wash endpoint.
- **Border** (`#EDEDED` / `--grey-200`): Hairline dividers, card borders.
- **Control border** (`#D4D4D4` / `--grey-300`): Secondary buttons, inputs, placeholders (not body text).
- **Ink secondary** (`#6E6E6E` / `--ink-secondary`): Secondary prose, meta text — minimum AA on canvas and surface.
- **Tertiary emphasis** (`#525252` / `--grey-600`): Strong secondary prose, ghost button text.
- **Decoration muted** (`#A3A3A3` / `--grey-400`): **Decoration only** — "Them" bubble outline, idle dots, bullets; never body text.

### v2 — Accent & semantic state (rehaul 2026-07-08)

A deliberate version bump from total chromatic silence to **restrained** color. All OKLCH, all WCAG-verified; text roles ≥4.5:1 and graphic roles ≥3:1 on both `--canvas` and `--grey-50`.

- **Accent — deep ink-blue** (`--accent` `oklch(45% 0.12 250)`): primary buttons, links, current selection, focus ring. Doubles as button fill (white text = 7.44:1) and link text on white (7.44:1). `--accent-strong` for hover/pressed; `--accent-muted` for the selected-nav wash / subtle tint; `--accent-border` for borders on tinted surfaces; `--on-accent` (`#FFFFFF`) for text on a fill. **Keep accent ≤8% of surface area.**
- **Live** (`--live` `oklch(55% 0.2 25)`): recording dot/ring; `--live-strong` for "Recording" text.
- **Semantic** success / warning / error, each a triad: `-text` (readable text on canvas), base (icon/dot/border graphic), `-bg` (subtle message tint). `--info-*` reuses the accent family.

### Named Rules

**The Chromatic Silence Rule (v2).** Hue is permitted for **state and one accent only** — primary action, selection, live capture, and semantic success/warning/error. Decoration stays monochrome; never a color wash for flavor. Naomi keeps her dedicated surfaces.

**The Accent Budget Rule.** The ink-blue accent covers ≤8% of any screen. If a screen looks blue, an inactive element is wrongly accented.

**The AA Secondary Rule.** Any readable secondary text uses `--ink-secondary` or darker — never `--grey-400`.

## Typography

**Display font:** Space Grotesk 600 (system fallback stack)  
**Body font:** Inter 400/500/600  
**Evidence font:** JetBrains Mono 400/500 — transcripts, paths, ledger (scope to narrow over time per rehaul plan)

**Character:** Editorial confidence in headings; neutral, readable UI body; monospace reserved for "typed evidence."

### Hierarchy

- **Hero display** (SG 600, 56px / 1.0, −0.04em): Onboarding and brand moments only.
- **Page display** (SG 600, 40px / 1.1, −0.03em): Empty states, Ask hero.
- **Title** (SG 600, 28px / 1.2, −0.02em): Screen and note titles.
- **Section** (SG 600, 20px / 1.3, −0.02em): Section headings.
- **Emphasis body** (Inter 500, 16px / 1.5): Row titles, card titles.
- **Body** (Inter 400, 14px / 1.6): Default UI copy; cap line length 65–75ch in prose blocks.
- **Transcript** (JB Mono 400, 13px / 1.6): Live and stored transcript segments.
- **Meta / label** (JB Mono 400–500, 12px / 1.5, 0.08em caps today): Timestamps, paths — **migrate to Inter 500 sentence case in rehaul.**

### Named Rules

**The Evidence Mono Rule.** Monospace is for transcript content and technical identifiers — not for every section label in the app shell.

## Elevation

Flat-by-default surfaces on white. Depth is conveyed by borders, `--grey-50` fills, and a **single** float shadow — not stacked card shadows.

### Shadow Vocabulary

- **Float** (`0 8px 24px rgba(0,0,0,0.08)` / `--shadow-float`): Answers panel, dictation pill, popovers, tray menu, toast.
- **Knob** (`0 1px 3px rgba(0,0,0,0.15)` / `--shadow-knob`): Toggle knob off state.
- **Keycap** (`0 1px 0 #D4D4D4` / `--shadow-keycap`): Hotkey keycaps in Settings.

**Permitted wash:** `linear-gradient(#FFFFFF, #F7F7F7)` vertical only (`--wash-surface`).

### Named Rules

**The One Shadow Rule.** `--shadow-float` is the only large elevation shadow. Do not add ad-hoc drop shadows on cards.

## Components

Tactile and restrained — controls read as precise instruments, not marketing chrome.

### Buttons

- **Shape:** `--radius-control` (8px).
- **Primary:** `--ink` fill, `--canvas` text; hover via opacity/weight, not new colors.
- **Secondary / ghost:** `--canvas` or transparent with `--control-border` or `--ink` border; active border `--ink`.
- **Motion:** `--dur-micro` (180ms) `--ease-out` on transform/opacity.

### Cards / Containers

- **Corner:** `--radius-card` (12px).
- **Background:** `--canvas`; optional `--grey-50` hover rows inside lists.
- **Border:** 1px `--border` default; 1px `--ink` when selected/active.
- **Padding:** `--space-6` (24px) internal default.
- **No nested cards** — use list rows, dividers, or panels.

### Inputs / Fields

- **Border:** 1px `--control-border` empty; 1px `--ink` when filled/focused.
- **Placeholder:** `--control-border` color — verify contrast if used as visible text.
- **Radius:** `--radius-control`.

### Navigation (nav rail)

- Active row: `--grey-50` fill; ink icon/wordmark.
- Labels: migrating from mono uppercase to Inter 500 sentence case (rehaul).

### Live capture affordances

- **Breathing ring:** `omniBreathe` 2.4s ease-in-out — only while capture is live.
- **Dictation pill:** float shadow, pill radius 999px.

### Loading

- **Shimmer skeleton:** `omniShimmer` on grey gradient bars — never spinners on primary surfaces.

## Do's and Don'ts

**Do**

- Consume `apps/ui/src/styles/tokens.css` variables exclusively in components.
- Use `--ink-secondary` for secondary readable text.
- Respect `prefers-reduced-motion` (global freeze in tokens).
- Keep transcript and citation UI in mono; keep marketing/onboarding in Space Grotesk.
- One primary CTA per screen.

**Don't**

- Add hue to v1.0 surfaces without updating this file and PRODUCT.md together.
- Use `--grey-400` for body or label text.
- Use gradient text, side-stripe borders, or nested card grids.
- Show engine diagnostics (`stt_engine`, latency ms) in default chrome — Advanced only.
- Uppercase mono "eyebrow" labels on every settings section (rehaul target).

**Source files:** `docs/design/design-brief.md` · `docs/design/design-components.md` · `apps/ui/src/styles/tokens.css`
