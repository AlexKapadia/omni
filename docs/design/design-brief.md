# Omni Design Brief — Extracted Design Contract

**Source of truth:** `docs/design/reference/Omni Design.dc.html` (v1.0, "1440 primary canvas · single source of truth for Claude Code").
Every value in this brief is quoted exactly from that file. Defaulted values (where the file is silent) are explicitly marked `DEFAULTED`.
Component-level specs (per-screen) live in `docs/design/design-components.md`. CSS tokens live in `apps/ui/src/styles/tokens.css`.

**Core rule (verbatim from cover):** "One rule everywhere: white canvas, black and grey only. State is weight, scale, motion and depth — never hue."

---

## 1. Palette — "total chromatic silence"

Strictly monochrome. Seven swatches are defined in the doc, plus two doc-canvas-only values.

| Hex | Role (verbatim) | Token |
| --- | --- | --- |
| `#FFFFFF` | canvas | `--canvas` |
| `#F7F7F7` | surface | `--grey-50` |
| `#EDEDED` | border / divider | `--grey-200` |
| `#D4D4D4` | disabled | `--grey-300` |
| `#A3A3A3` | secondary · "Them" | `--grey-400` |
| `#525252` | tertiary emphasis | `--grey-600` |
| `#0A0A0A` | ink | `--ink` |

**NOT in-app colors (design-doc canvas only):**
- `#E8E8E8` — the design document's page background. Never an app surface.
- `#E2E2E2` — the 1px border around each 1440px screen frame in the doc, with shadow `0 8px 32px rgba(0,0,0,0.06)`. Both are doc-canvas framing, not app chrome.

**Washes & shadows (in-app):**
- Max permitted wash: `linear-gradient(#FFFFFF, #F7F7F7)` vertical — "max permitted wash". Used on: transcript column, collapsed-transcript bar.
- The only float shadow: `0 8px 24px rgba(0,0,0,0.08)` — "shadow/float … the only shadow". Used on: answers panel, dictation pill, popovers, tray menu, toast, people-card hover.
- Toggle knob (off state): `box-shadow: 0 1px 3px rgba(0,0,0,0.15)` on the white knob.
- Keycap: `box-shadow: 0 1px 0 #D4D4D4` (Settings hotkey keys).

**Semantic uses observed:** "Them" transcript text/border is `#A3A3A3`; "Me" is `#0A0A0A`. Placeholder/ghost text is `#D4D4D4`. Meta/timestamps/labels are `#A3A3A3`. Secondary prose is `#525252`.

## 2. Typography

Families (doc loads Google Fonts; app will self-host — see tokens.css note):
- **Display:** `'Space Grotesk', sans-serif` — weights loaded 500/600/700; **only 600 is used** in the doc.
- **Body:** `'Inter', sans-serif` — weights 400/500/600.
- **Mono:** `'JetBrains Mono', monospace` — weights 400/500.

Type scale (exact, from the "Type scale" table):

| Size / line-height | Name | Spec (verbatim) |
| --- | --- | --- |
| 56 / 1.0 | Hero display | Space Grotesk 600 · −0.04em · onboarding, brand only |
| 40 / 1.1 | Page display | Space Grotesk 600 · −0.03em · empty states, Ask |
| 28 / 1.2 | Note title | Space Grotesk 600 · −0.02em · note + screen titles |
| 20 / 1.3 | Section heading | Space Grotesk 600 · −0.02em |
| 16 / 1.5 | Emphasis body | Inter 500 · 0em — row titles, card titles |
| 14 / 1.6 | Body | Inter 400 · 0em · `#0A0A0A` / `#525252` — UI default, note prose |
| 13 / 1.6 | Transcript | JetBrains Mono 400 · 0em — "typeset evidence, always mono" |
| 12 / 1.5 | Meta | JetBrains Mono 400–500 · `#A3A3A3` — timestamps, paths, ledger; labels 0.08em caps |

**Label convention (everywhere):** section labels are JetBrains Mono 11px, `letter-spacing: 0.08em`, `text-transform: uppercase`, `#A3A3A3` (e.g. "TRANSCRIPT", "CREATE EVENT", "AI ROUTER").
Other observed sizes (component-local, not scale levels): 34px lockup wordmark (−0.03em), 17px rail wordmark, 15px input/answer prose, 13px button-small/captions, 12.5px live-transcript mono, 11px labels, 10px in-bubble timestamps, 24px pairing code (0.15em tracking), 32px mobile timer mono.

## 3. Spacing

Doc scale (px, with verbatim roles): **4** hairline gaps · **8** inside controls · **12** control padding · **16** between rows · **24** card padding · **32** section gap · **48** page margin · **64** canvas breathing room.

Token mapping: `--space-N = N × 4px` (so `--space-1`=4, `--space-2`=8, `--space-3`=12, `--space-4`=16, `--space-6`=24, `--space-8`=32, `--space-12`=48, plus `--space-16`=64). Intermediate steps (5,7,9,10,11) exist for arithmetic completeness and are `DEFAULTED` (the doc's stated scale skips them, though 20/18/28/40/56 paddings do appear in components).

## 4. Radii

Verbatim: "4 chips · 8 controls · 12 cards · 999 pills".
- `--radius-chip: 4px` (also skeleton bars)
- `--radius-control: 8px` (buttons, inputs, nav rows, hover rows, pair-code box)
- `--radius-card: 12px` (cards, panels, popovers, tray, toast)
- `--radius-pill: 999px` (pills, toggles, chips, progress tracks, collapsed answers)
- Also observed: `6px` keycaps (Settings hotkey), `10px` transcript "Them" bubbles, `50%` ring dots/record button.

## 5. Borders

- Default hairline: `1px solid #EDEDED` (cards, dividers, rows).
- Interactive/control border: `1px solid #D4D4D4` (secondary button, search field, empty ask-input, radius demos).
- Active/focused/selected: `1px solid #0A0A0A` (ask input filled, chosen vault path, Grant/Connect/Stop outline buttons, pairing code).
- Transcript "Them" bubble: `1px solid #A3A3A3`.
- Woven-context indent: `border-left: 2px solid #EDEDED` with `padding-left: 20px` (desktop) / `14px` (mobile).
- Table header rule: `border-bottom: 1px solid #0A0A0A` (motion table, router matrix, ledger).

## 6. Motion

Keyframes (exact, from the doc `<style>` block):

```css
@keyframes omniBreathe { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
@keyframes omniAperture { 0%, 74%, 100% { transform: rotate(-8deg) scale(1); } 82% { transform: rotate(22deg) scale(0.55); } 90% { transform: rotate(-8deg) scale(1); } }
@keyframes omniShimmer { 0% { background-position: -320px 0; } 100% { background-position: 320px 0; } }
```

Applied animation values (from the doc's runtime script):
- Breathe: `omniBreathe 2.4s ease-in-out infinite`
- Aperture (doc demo loop): `omniAperture 5.6s cubic-bezier(0.4,0,0.2,1) infinite`, `transform-origin: 50px 50px` (the active gesture occupies 74%→90% of 5.6s ≈ the 900ms one-shot spec)
- Shimmer: `omniShimmer 1.6s linear infinite` on `linear-gradient(90deg,#F7F7F7 25%,#EDEDED 50%,#F7F7F7 75%)`, `background-size: 640px 100%`, bar height 14px, radius 4px — "never a spinner on primary surfaces"

Motion spec table (exact, all columns verbatim):

| name | duration | easing | properties | notes |
| --- | --- | --- | --- | --- |
| micro-interaction | 180ms | cubic-bezier(0,0,.2,1) | transform, opacity | hover, press, toggle |
| view transition | 300ms | cubic-bezier(0,0,.2,1) | transform, opacity | route changes, panel open |
| breathing ring | 2400ms loop | sine (ease-in-out) | opacity 1 → .55 | only while capture is live; the only permanent animation |
| enhance moment | 250ms / line | cubic-bezier(0,0,.2,1) | opacity 0→1, y +6→0 | AI lines settle between user lines, 80ms stagger; user lines never move |
| answers panel hit | 200ms | cubic-bezier(0,0,.2,1) | y +8→0, opacity, shadow | shadow blooms 0 → 0 8px 24px rgba(0,0,0,.08); no bounce |
| approve card | 300ms | cubic-bezier(.4,0,.2,1) | scale, travel, opacity | card compresses to black check chip, files itself into the note |
| logo aperture | 900ms | cubic-bezier(.4,0,.2,1) | rotate +30°, scale .55 | launch + onboarding only |
| global rules | 60fps | — | transform/opacity only | honour prefers-reduced-motion: freeze all loops, keep end states |

Additional timings observed: toggle "120ms travel"; toast/popover "rises 8px / 200ms"; capture toast "auto-dismisses in 30s · never auto-starts".
`--dur-micro: 180ms` and `--dur-page: 300ms` are **extracted** (not defaulted). Easing token `--ease-out: cubic-bezier(0,0,.2,1)`, `--ease-in-out: cubic-bezier(.4,0,.2,1)`.

## 7. Logo construction

One ring, three readings (verbatim): "a camera aperture (it sees), a speaker ring (it hears), an orbit (omni). One colour, black on white, no exceptions. The ring at 8px scale is the live-capture heartbeat everywhere in the product."

- **Primary mark:** SVG `viewBox="0 0 100 100"`, `<circle cx="50" cy="50" r="38" fill="none" stroke="#0A0A0A" stroke-width="11" stroke-dasharray="29.8 9.99" transform="rotate(-8 50 50)">`. Geometry: 6 segments — circumference 2π·38 = 238.76; (29.8 + 9.99) × 6 = 238.74 ✓. Caption: "6 segments · r38 · stroke 11 · rot −8°".
- **Tray variant (16px true size):** same viewBox, `r="34" stroke-width="20" stroke-dasharray="54 17.2"` rotate(−8). 3 segments — 2π·34 = 213.63; (54 + 17.2) × 3 = 213.6 ✓. "3 segments · heavier stroke".
- **Horizontal lockup:** 44px mark + "Omni" in Space Grotesk 600 34px −0.03em; "gap = 0.4 × mark width · baseline-centred".
- **Animated variant:** primary mark + `omniAperture` — "rotate +30° · contract to 55% · open · 900ms · launch + onboarding only".
- **Breathing ring (heartbeat dot):** small circle, `border: 2.5px solid #0A0A0A; border-radius: 50%` at 10px (2px border at 8px, 3px at 12px, 4–5px larger), animated `omniBreathe 2.4s` — "opacity 100 → 55% · 2.4s sine · the only permanent animation". Appears in: capture bar, answers pill, tray menu, paired devices, mobile recording, live notepad caret.

## 8. Waveform (canvas component)

Verbatim: "2.5px bars · ink on white · driven by real levels · fast attack (0.5), damped decay (0.93) so it feels physical · floor 2px".
From the reference implementation: bar width 2.5px, even gaps `(w − bars·2.5)/(bars−1)`, vertically centered; idle floor level 0.06→min height 2px; attack `lv += (target−lv)·0.5`, decay `lv·0.93`. Sizes used: design-system demo 320×32 (52 bars), live meeting 280×26 (44), phone 220×36 (36), dictation pill 110×18 (20). **Meter mode** (onboarding mic check): track `#EDEDED`, fill `#0A0A0A`, 200×6px, min fill 2px, attack 0.3 / decay 0.06. Honors `prefers-reduced-motion` (renders inactive).

## 9. Screens defined in the design doc

| # | Doc id | Label | Maps to app milestone |
| --- | --- | --- | --- |
| — | `cover` | Cover | brand reference only |
| 01 | `logo` | Logo suite | brand assets, tray icon |
| 02 | `system` | Design system | this brief + tokens.css |
| 03 | `library` | Library — home | main window home (rail + meeting list) |
| 04 | `live` | Live meeting — flagship | **Live Meeting** (notepad + transcript + answers + capture bar) |
| 05 | `note` | Post-meeting note — enhance + approvals | note view + **Approval cards** rack |
| 06 | `ask` | Ask Omni — answer + empty state | **Ask Omni** |
| 07 | `pill` | Dictation pill — idle / listening / command / approval popover | **Dictation pill** (global push-to-talk) |
| 08 | `people` | People | People screen |
| 09 | `onboarding` | Onboarding — a two-minute ritual (4 steps) | **Onboarding** |
| 10 | `settings` | Settings — router + ledger | **Settings** |
| 11 | `tray` | Tray menu + capture toast | tray + toast |
| 12 | `mobile` | Mobile companion (3 phone screens) | future scope — not desktop v1 |
| 13 | `connections` | Connections — calendar, mail, contacts, paired devices | Settings/Connections |

## 10. Design principles distilled from the doc

1. Monochrome absolutism — state is expressed by weight, scale, motion, depth; never hue. Even success ("✓ Granted", "✓ Connected") is black.
2. One shadow, one wash, one permanent animation (the breathing ring, only while capture is live).
3. Mono type = machine evidence (transcripts, timestamps, paths, ledgers); Inter = human UI; Space Grotesk = titles only, always 600.
4. "Your lines never move" — user-authored text is visually primary (`#0A0A0A`, 500) and positionally stable; AI text settles around it, indented, `#525252`, behind a 2px `#EDEDED` left border.
5. Approval language is identical everywhere: mono uppercase label → title (Inter 500 14px) → mono detail (`#525252`) → [Approve (primary)] [Edit (ghost `#525252`)] [Dismiss (ghost `#A3A3A3`)].
6. Skeleton shimmer, never spinners, on primary surfaces.
7. Privacy copy is a UI element: "Answers come from your vault only. Nothing leaves this device." / "No bot joins your calls." / "never sends".

## 11. Notes, discrepancies & provenance

- No prompt-injection-style content was found in the reference files; all text is design copy.
- **Copy drift vs. product architecture (flag for CTO, layout unaffected):** onboarding step 4 lists models `whisper-large-v3-turbo / bge-small-en-v1.5 / silero-vad` (project spec says Parakeet-TDT, not Whisper); the Settings router matrix columns read `local / anthropic / openai` (project spec routes Groq / Gemini / Claude). Adopt the *layouts*; the copy/data must come from the real engine contracts.
- `support.js` is the dc-runtime (generated; ignored except to confirm rendering). `ios-frame.jsx` is a generic iOS device frame used only for the mobile-companion mock — not Omni design language.
- Doc props (interactive states the doc itself toggles): `motionOn`, `answersOpen`, `approvedState` — these confirm the intended state pairs (answers panel ⇄ collapsed pill; approval card ⇄ "✓ Event created" chip).
