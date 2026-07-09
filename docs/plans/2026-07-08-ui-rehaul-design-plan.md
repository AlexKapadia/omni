# UI Rehaul & Rebrand Plan — Hybrid Omni Product

**Date:** 2026-07-08  
**Method:** Impeccable design skill (`/impeccable shape`, `clarify`, `distill`, `onboard`, `typeset`, `colorize`)  
**Status:** Proposal — no code changes yet  
**Impeccable:** Installed to `.cursor/skills/impeccable/` · `PRODUCT.md` + `DESIGN.md` at repo root (2026-07-08)

---

## Executive summary

Omni is now a **hybrid product**: meeting capture + library (Meetily parity), global dictation, voice agent (Naomi), vault-native notes, and cross-platform shells. The **engine is mature**; the **UI still reads like a developer console** — monospace labels everywhere, engineer jargon (“STT”, “AI router”, “kill switch”), and a strict monochrome system that communicates “tool” more than “trusted companion.”

This plan proposes:

1. A **name decision** (keep Omni, adopt Omni+, or rebrand)
2. A **visual system evolution** (still local-first and calm, but warmer and more legible)
3. A **copy & IA overhaul** (human language, progressive disclosure)
4. A **phased implementation roadmap** mapped to real files

**North star:** *A user fluent in Notion or Granola should sit down and trust this app in under 60 seconds — without reading a manual.*

---

## 1. Diagnosis (Impeccable critique)

### What works (preserve)

| Strength | Where |
|----------|--------|
| Local-first privacy story | Onboarding welcome, vault step |
| Token-driven consistency | `apps/ui/src/styles/tokens.css` |
| Real engine wiring (no mocks) | All screens |
| Breathing ring + pill affordances | Live nav, dictation |
| Approval-before-execute | Naomi / action cards |
| Skeleton shimmer (no spinners) | Loading states |

### What fails the “product slop test”

Per Impeccable **product register**: failure mode is *strangeness without purpose*, not flatness. Current issues:

| Problem | Symptom | Example |
|---------|---------|---------|
| **Console aesthetic** | JetBrains Mono on nav labels, settings, footer, latency | `stt parakeet/cuda`, `AI ROUTER` |
| **Engineer copy** | User must know our architecture | “Kill switch”, “BYOK”, “instant execute whitelist” |
| **Settings overload** | 12+ cards, equal visual weight | Router matrix + cost ledger in main flow |
| **Live screen density** | Everything visible at once | Notepad + transcript + 4 side panels |
| **Onboarding as setup wizard** | 6 technical steps before value | Keys, models, calendar before first capture |
| **Name drift** | Roadmap says Omni+, app says Omni | No unified product story |

### Impeccable command mapping

| Phase | Impeccable command | Target |
|-------|-------------------|--------|
| 0 | `init` | `PRODUCT.md`, `DESIGN.md` |
| 1 | `clarify` | All user-facing strings |
| 2 | `distill` | Settings, Live meeting, Library detail |
| 3 | `typeset` | Typography roles (mono scope) |
| 4 | `colorize` | Restrained accent + semantic states |
| 5 | `onboard` | First-run → first meeting notes |
| 6 | `layout` | Spacing, hierarchy, responsive |
| 7 | `polish` + `audit` | Ship pass (a11y, contrast) |
| 8 | `live` | Browser variant iteration |

---

## 2. Naming & positioning

### Product story (one sentence)

> **Your meetings and voice notes stay on your device — transcribed, searchable, and turned into notes you approve before anything leaves.**

### Name options (decision required)

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **A. Omni** (evolve) | Existing brand, aperture mark, MIT repo | Generic; doesn’t signal hybrid | **Default if minimizing churn** |
| **B. Omni+** | Matches roadmap; signals “enhanced fork” | “Plus” feels incremental; awkward in window title | Good for internal/dev docs only |
| **C. Recall** | Memorable, verb, consumer-friendly | Full rebrand cost; domain/trademark | Strong consumer pitch |
| **D. Hearth** | Warm, private, “home for your thoughts” | Less “meeting” connotation | Good if dictation-first story wins |

**Recommended path:** **Keep “Omni”** as the legal/product name, introduce a **consumer tagline** everywhere the wordmark appears:

| Context | Current | Proposed |
|---------|---------|----------|
| Window / installer | Omni | Omni |
| Tagline (nav, onboarding) | (none) | **Meeting notes that stay yours** |
| Sub-brand for hybrid | Omni+ (docs only) | Drop from UI; use “Omni” consistently |

If you want a **full rebrand**, run a separate decision workshop before Phase 1 — it touches `tauri.conf.json`, `OmniMark`, npm/cargo names, and GitHub releases.

### Feature naming (human, not internal)

| Internal / current | User-facing |
|--------------------|-------------|
| Live meeting | **Record** or **In a meeting** |
| Library | **Meetings** |
| Ask Omni | **Ask** |
| Dictation | **Voice notes** |
| Naomi | **Naomi** (keep — character name is fine) |
| Settings → AI router | **Settings → AI providers** |
| Kill switch | **Pause all cloud AI** |
| Instant execute | **Auto-run safe actions** |
| Transcription engine | **Transcription quality** |
| STT / Parakeet / Whisper | **Fast (on-device)** / **Enhanced** / **Cloud** (already tiered — hide model names by default) |
| Me / Them streams | **You** / **Everyone else** |
| Engine unavailable | **Omni isn’t running** |

---

## 3. Visual design direction

### Register & color strategy

**Impeccable register:** `product` (tool serves the task).  
**Color strategy:** **Restrained** → light evolution from strict monochrome:

- **Keep** white/near-white canvas (local-first, calm, not “AI cream/sand”)
- **Add** one accent: deep ink-blue or soft teal at ≤8% of surface area (primary buttons, live indicator, links)
- **Add** semantic tints (OKLCH): success, warning, error — never hue for decoration alone
- **Break** the “total chromatic silence” rule *intentionally* for state only (live recording dot, errors, Naomi presence)

Scene sentence (forces light theme):

> *A knowledge worker at their desk in daylight, glancing between a video call and a quiet sidebar — they need calm focus, not a flashy dashboard.*

### Typography (`/impeccable typeset`)

| Role | Current | Proposed |
|------|---------|----------|
| UI default | Inter + mono meta | **Inter only** for UI |
| Section labels | 11px UPPERCASE mono | **13px sentence case Inter 500** — no uppercase eyebrows |
| Transcript | JetBrains Mono ✓ | **Keep mono** — evidence layer |
| Timestamps / IDs | Mono | **Tabular nums Inter** or mono only in debug mode |
| Display / wordmark | Space Grotesk | **Keep** — brand anchor |

**Self-host fonts** (`fonts.css`) — already planned in tokens; ship in Phase 2.

### Layout principles (`/impeccable layout` + `distill`)

1. **One primary action per screen** (bold primary button, ghost everything else)
2. **Settings:** two tiers — **Essentials** (80% of users) vs **Advanced** (router, ledger, hotkeys)
3. **Live meeting:** collapsible panels; default = transcript + slim capture bar
4. **Library:** card rows → softer list with title, date, duration; detail pane stays tabbed
5. **No nested cards** (Impeccable ban)
6. **Status footer:** slim “Connected · On-device transcription ready” — hide `stt_engine/device` behind tooltip or Advanced

### Motion (`/impeccable animate`)

- Keep 180–300ms ease-out; respect `prefers-reduced-motion`
- Live breathing ring: keep — it conveys state
- Remove latency numbers from default UI (power users: Settings → Advanced → Diagnostics)

### Iconography & mark

- **OmniMark** aperture: keep geometry, optionally soften stroke on light backgrounds
- Add **simple line icons** beside nav items (library, mic, chat, waveform, gear) — Lucide or Phosphor, 1.5px stroke, ink color

---

## 4. Information architecture

### Proposed nav (6 → 5 items)

```
Meetings     (was Library)     — home default
Record       (was Live)        — start / in-progress capture
Ask          (was Ask Omni)
Voice notes  (was Dictation)
Naomi        (unchanged)
─────────────
Settings
```

Footer: `Your data stays on this device` (keep trust line)

### Settings restructuring

**Essentials tab (default)**

| Group | Contents |
|-------|----------|
| Your voice | Speaker identity (rename from “Your voice in meetings”) |
| Notes folder | Vault path |
| Transcription | Accuracy tier (Fast / Enhanced / Cloud) |
| Privacy | Pause cloud AI, keep audio, disclosure reminder |
| Calendar | Google / Microsoft connect |
| Templates | Note layout + custom templates |

**Advanced tab**

| Group | Contents |
|-------|----------|
| AI providers | Keys, provider matrix (collapsed by default) |
| Usage | Cost + latency ledger |
| Automation | Auto-start, silence auto-stop, detection |
| Devices | Mic / output labels, hotkey |
| Diagnostics | Engine version, STT device, export logs |

### Onboarding rewrite (`/impeccable onboard`)

**Goal:** First enhanced note in **≤3 minutes**, not full system configuration.

| Step | Current | Proposed |
|------|---------|----------|
| 1 | Welcome + truths | Welcome + **“Record your first meeting”** CTA |
| 2 | Speaker identity | Optional — “Skip, I’ll do this later” |
| 3 | Vault | Default `~/Documents/Omni` with one-click accept |
| 4–6 | Keys, models, calendar | **Defer** to Settings with contextual prompts when feature is first used |

**Aha moment:** User sees a real transcript + enhanced note from a 30-second test recording.

---

## 5. Screen-by-screen changes

### Meetings (Library)

- Hero empty state: illustration + **“Import a recording or start one live”**
- Row: title (emphasis), relative date (meta), duration badge
- Detail tabs: **Summary · Transcript · Chat · Export** (rename Tools → Export)
- Export tab: icon buttons with labels (PDF, Word, Markdown, Subtitles)

### Record (Live)

- Top: meeting title (editable) + **Recording** pill (red dot when live)
- Center: transcript stream (dominant)
- Bottom bar: Stop · Enhance notes · (overflow: translation, captions)
- Side panels: **collapsed drawers** — Answers, Summary, Vault suggestions

### Ask

- Headline: **“Ask about your meetings”** not latency breakdown
- Scope chips: **All meetings · This meeting · Voice notes**
- Citations: keep chips; hide `retrieval_ms` unless debug

### Voice notes (Dictation history)

- Card list: cleaned text preview, date, mode chip (Note / Pasted / Command)
- Empty: **“Hold F9 anywhere to capture a thought”** (platform-specific hotkey in settings)

### Naomi

- Keep character; soften debug affect labels for users
- Approval cards: plain-language action titles

### Dictation pill (separate window)

- Chips: **Note · Command · Paste** (not NOTE/COMMAND/INSERT)
- Locked state: padlock icon + “Still listening”
- Hide `stt · clean · insert · total` latency strip by default

### Status footer

| Current | Proposed |
|---------|----------|
| `engine running` | `Ready` |
| `connecting to engine` | `Starting…` |
| `engine unavailable` | `Omni isn’t running` |
| `stt parakeet/cuda` | (removed — Advanced only) |
| `367 ms` | `Connected` or hide |

---

## 6. Design system deliverables

Run `/impeccable init` then `/impeccable document` to generate:

| Artifact | Purpose |
|----------|---------|
| `PRODUCT.md` | Register, users, anti-references, principles |
| `DESIGN.md` | OKLCH palette, type scale, component specs |
| `apps/ui/src/styles/tokens.css` | v2 tokens (additive — don’t rename existing) |
| `apps/ui/src/styles/fonts.css` | Self-hosted Space Grotesk + Inter |
| `docs/design/component-catalog.md` | Button, input, card, nav, empty state patterns |

### New tokens (additive)

```css
/* Proposed — implement in Phase 2 */
--accent: oklch(45% 0.12 250);        /* primary actions, links */
--accent-muted: oklch(95% 0.02 250);  /* selected nav wash */
--live: oklch(55% 0.2 25);            /* recording indicator */
--success / --warning / --error      /* semantic, WCAG-checked */
```

---

## 7. Implementation phases

### Phase 0 — Foundation (1 week)

- [x] Run `/impeccable init` — capture PRODUCT.md + DESIGN.md (2026-07-08)
- [ ] Stakeholder sign-off: **name** (Omni vs rebrand) + **accent color**
- [ ] Create `copy/glossary.json` — single source for UI strings
- [ ] Add Impeccable hook: `node .cursor/skills/impeccable/scripts/hook.mjs` (already in `.cursor/hooks.json`)

### Phase 1 — Copy & clarify (1–2 weeks)

**Impeccable:** `clarify` on all screens  
**Files:** `nav-rail.tsx`, `status-footer.tsx`, `settings-screen.tsx`, `onboarding/step-*.tsx`, `transcription-backend-section.tsx`, `privacy-section.tsx`, `library-screen.tsx`, `live-meeting-screen.tsx`, `ask-screen.tsx`, `dictation-history-screen.tsx`, `dictation-pill-view.tsx`

- [ ] Replace jargon per glossary (§2)
- [ ] Sentence-case all section labels; remove uppercase mono eyebrows
- [ ] Error messages: what / why / fix formula

### Phase 2 — Typography & tokens (1 week)

**Impeccable:** `typeset`, `colorize`  
**Files:** `tokens.css`, `app.css`, `section-label.tsx`, `fonts.css` (new)

- [ ] Self-host fonts
- [ ] Restrict `--font-mono` to transcript + code blocks + ledger tables
- [ ] Add accent + semantic colors; verify contrast ≥4.5:1
- [ ] Nav icons (Lucide)

### Phase 3 — IA & settings distill (2 weeks)

**Impeccable:** `distill`, `layout`  
**Files:** `settings-screen.tsx`, new `settings-essentials.tsx` / `settings-advanced.tsx`, `App.tsx`

- [ ] Split Settings Essentials / Advanced
- [ ] Move router matrix + cost ledger to Advanced
- [ ] Rename nav items (§4)
- [ ] Update `SectionId` types + tests

### Phase 4 — Onboarding & empty states (1 week)

**Impeccable:** `onboard`  
**Files:** `onboarding-wizard.tsx`, `library-screen.tsx`, `dictation-history-screen.tsx`

- [ ] Shorten onboarding to 3 steps + deferrals
- [ ] Optional test recording step
- [ ] Empty states with illustration + single CTA

### Phase 5 — Live & Library polish (2 weeks)

**Impeccable:** `layout`, `animate`, `delight`  
**Files:** `live-meeting-screen.tsx`, `library-meeting-detail-pane.tsx`, panel components

- [ ] Collapsible side panels on Live
- [ ] Softer meeting list rows
- [ ] Export tab polish
- [ ] Micro-delight: subtle confetti on first finalized note (reduced-motion: toast only)

### Phase 6 — Shell & platform (1 week)

**Files:** `tauri.conf.json`, installer copy, tray menu, `engine_sidecar` error strings

- [ ] Update `longDescription` / installer strings for cross-platform
- [ ] macOS menu bar / Linux tray labels (human copy)
- [ ] App icon refresh (optional — keep aperture or simplify)

### Phase 7 — Ship quality (1 week)

**Impeccable:** `audit`, `polish`, `harden`

- [ ] WCAG 2.2 AA pass (contrast, focus rings, aria)
- [ ] Responsive: min width 900 → test 768 tablet
- [ ] i18n-ready strings (extract to glossary)
- [ ] Visual regression: `/impeccable live` on Home, Record, Settings
- [ ] Update Vitest snapshots + `setup-settings` label tests

**Total estimate:** 8–10 weeks (can parallelize Phase 1–2)

---

## 8. Anti-references (Impeccable PRODUCT.md)

Do **not** look like:

- Generic AI SaaS (purple gradients, hero metrics, glass cards)
- Developer tools exposed to consumers (Grafana, raw AWS console)
- Dense admin dashboards (everything in tables)
- “AI slop” eyebrows (`TRANSCRIPT`, `SETTINGS` on every section)
- Talkis/Meetily clones (we have parity; identity should be **Omni**: vault + approval + local-first)

**Anchor references** (specific things to borrow):

| Reference | Borrow |
|-----------|--------|
| **Granola** | Calm meeting list, minimal chrome |
| **Notion** | Settings clarity, empty states |
| **Linear** | Density when needed, crisp hierarchy |
| **Apple Voice Memos** | Voice notes list simplicity |
| **Obsidian** | Vault trust, no cloud vibes |

---

## 9. Success metrics

| Metric | Target |
|--------|--------|
| Onboarding completion | ≥70% (vs defer-heavy today) |
| Time to first enhanced note | <3 min |
| Settings page scroll depth | 80% never open Advanced |
| Support-style confusion | Zero “what is STT/engine” in user testing |
| Impeccable critique score | ≥85/100 post-Phase 7 |

---

## 10. Immediate next steps

1. **You decide:** Omni (evolve) vs full rebrand (§2)
2. **Run in Cursor:** `/impeccable init` — generates `PRODUCT.md` + `DESIGN.md` from this plan
3. **Run:** `/impeccable critique apps/ui/src/screens/library-screen.tsx` for baseline score
4. **Run:** `/impeccable shape settings-restructure` before Phase 3 code
5. **Pin useful commands:**
   ```bash
   node .cursor/skills/impeccable/scripts/pin.mjs pin clarify
   node .cursor/skills/impeccable/scripts/pin.mjs pin distill
   ```

---

## Appendix A — File change index (implementation)

| Area | Primary files |
|------|----------------|
| Tokens / theme | `apps/ui/src/styles/tokens.css`, `app.css`, `fonts.css` |
| Nav / shell | `nav-rail.tsx`, `App.tsx`, `status-footer.tsx` |
| Copy source | `copy/glossary.json` (new), settings + onboarding components |
| Settings | `settings-screen.tsx`, `*-section.tsx` under `components/settings/` |
| Onboarding | `onboarding-wizard.tsx`, `step-*.tsx` |
| Meetings | `library-screen.tsx`, `library-meeting-detail-pane.tsx` |
| Record | `live-meeting-screen.tsx`, `capture-bar.tsx`, panel components |
| Pill | `dictation-pill-view.tsx`, `pill.css` |
| Tauri / install | `tauri.conf.json`, `packaging/README.md` |
| Tests | `*.test.tsx` for nav labels, footer, settings parse |

## Appendix B — Impeccable tooling installed

```text
.cursor/skills/impeccable/     # 23 design commands
.cursor/hooks.json             # Design detector on UI edits
```

Use `/impeccable` in chat for: `craft`, `shape`, `critique`, `audit`, `polish`, `clarify`, `distill`, `onboard`, `typeset`, `colorize`, `layout`, `delight`, `live`.
