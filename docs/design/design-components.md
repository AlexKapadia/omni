# Omni Design Components — Per-Screen Extraction

Companion to `design-brief.md`. Exact styles from `docs/design/reference/Omni Design.dc.html`.
All screens render on a 1440px-wide white canvas (`#FFFFFF`); heights: Library 900, Live 900, Note 960, Ask 900, People 760, Onboarding cards 560×560, Settings/Connections auto.

## Buttons (canonical set, from Design system §02)

| Variant | Style |
| --- | --- |
| Primary | `background:#0A0A0A; color:#FFFFFF; border:none; border-radius:8px; padding:10px 18px; Inter 14px 500` (small: `padding:8px 14px; 13px`; large/onboarding: `padding:12px 28px`) |
| Secondary | `background:#FFFFFF; color:#0A0A0A; border:1px solid #D4D4D4; border-radius:8px; padding:10px 18px; Inter 14px 500` (hover: `border-color:#0A0A0A`) |
| Ghost | `background:transparent; color:#525252; border:none; padding:10px 8px; Inter 14px 500` (dismiss variant: `color:#A3A3A3`) |
| Disabled | `background:#F7F7F7; color:#D4D4D4; border:none; border-radius:8px` |
| Outline pill | `background:#FFFFFF; color:#0A0A0A; border:1px solid #0A0A0A; border-radius:999px` (Grant `5px 14px 12px`, Connect `6px 16px 12px`, mobile Stop `12px 32px 14px`) |

Primary hover (Library "Quick note"): `transform:translateY(-1px)`.

## Toggle
`36×20px`, `border-radius:999px`; knob `16×16px #FFFFFF` inset 2px. On: track `#0A0A0A`, knob right. Off: track `#EDEDED`, knob left + `box-shadow:0 1px 3px rgba(0,0,0,0.15)`. "120ms travel".

## Skeleton shimmer
`height:14px; border-radius:4px; background:linear-gradient(90deg,#F7F7F7 25%,#EDEDED 50%,#F7F7F7 75%); background-size:640px 100%; animation:omniShimmer 1.6s linear infinite`. Staggered widths (80% / 60%).

## 03 · Library (home)
- **Left rail:** `width:224px; border-right:1px solid #EDEDED; padding:24px 16px`. Lockup: 22px mark + "Omni" Space Grotesk 17px 600 −0.02em, `gap:10px`.
- **Nav row:** `padding:9px 12px; border-radius:8px; 14px`. Active: `background:#F7F7F7; font-weight:600; color:#0A0A0A`. Inactive: `color:#525252`, hover `background:#F7F7F7`. Badge (Inbox count): mono 11px `#A3A3A3`, right-aligned.
- **Rail footer:** `border-top:1px solid #EDEDED; padding:16px 12px` — "All data on this device" 12px `#525252`, vault path mono 11px `#A3A3A3`, storage bar `height:3px` track `#EDEDED` / fill `#A3A3A3` radius 999px, "4.4 GB of 20 GB".
- **Main:** `padding:48px 64px`. Header: "Today" 28px title + mono 12px meta; primary button right.
- **Meeting row:** `grid-template-columns:88px 1fr 120px; gap:24px; padding:18px 16px; margin:0 -16px; border-top:1px solid #EDEDED; border-radius:8px`, hover `background:#F7F7F7`. Cells: time mono 12 `#A3A3A3` · title 15px 500 + summary 13px `#A3A3A3` · duration mono 12 `#A3A3A3` right. Upcoming meeting: time in ink, status "in 40 min" `#525252`.
- **Day divider:** mono 11px caps 0.08em `#A3A3A3`, `padding:40px 0 16px`.

## 04 · Live meeting (flagship)
- Layout: notepad `flex:2; padding:56px 72px` | transcript `flex:1; border-left:1px solid #EDEDED; background:linear-gradient(#FFFFFF,#F7F7F7)` | capture bar bottom.
- **Notepad:** title 28px + mono meta right; body 16px `line-height:2`; placeholder `#D4D4D4` "Type anything. Omni is listening." Caret: `1.5px × 20px #0A0A0A` inline-block, breathing animation.
- **Transcript header:** "TRANSCRIPT" label + "auto-scroll · hold to pause" mono 11 `#A3A3A3`, `padding:20px 24px 12px`.
- **Transcript stream:** mono 12.5px lh 1.6, `gap:12px`, `padding:8px 24px`. **Them:** left-aligned, `max-width:85%; border:1px solid #A3A3A3; border-radius:10px; padding:8px 12px; color:#A3A3A3`, timestamp block 10px. **Me:** right-aligned, no bubble, `color:#0A0A0A; text-align:right`, timestamp 10px `#A3A3A3`. Speaker line: "Them · 14:07:12" / "Me · 14:07:31".
- **Answers panel (open):** absolute `right:20px; bottom:20px; width:340px`, card radius 12, border `#EDEDED`, float shadow, `padding:20px; gap:10px`. Contents: "ANSWER" label + "Collapse" 12px `#A3A3A3`; quoted question 13px italic `#A3A3A3`; answer 14px lh 1.6 ink with `<strong>` facts; source footer mono 11 `#A3A3A3` above `border-top:1px solid #EDEDED` → "↳ vault/clients/northwind.md · 2025-07-14 renewal call".
- **Answers pill (collapsed):** `border-radius:999px; padding:8px 16px; 13px #525252` + 8px breathing ring, float shadow.
- **Capture bar:** `height:64px; border-top:1px solid #EDEDED; padding:0 32px; gap:24px` — 12px breathing ring (3px border) · timer mono 13px `00:42:17` · waveform 280×26 (44 bars) · "mic + system audio · on-device" mono 11 `#A3A3A3` · Stop = secondary button `margin-left:auto`.

## 05 · Post-meeting note
- Content column `width:820px; margin:0 auto`, page top pad 56px.
- Header: title 28px; template pills right — active: `border:1px solid #EDEDED; background:#F7F7F7; radius:999px; padding:4px 12px; 500 ink`; inactive: transparent border, hover `border-color:#EDEDED`. Meta line mono 12 `#A3A3A3`: "Mon Jul 6 · 14:00–14:47 · marcus, elena (northwind) · enhanced 14:48".
- **Enhanced note body:** 15px lh 1.9, `gap:6px`. User line: `color:#0A0A0A; font-weight:500`. Woven AI context: `color:#525252; padding-left:20px; border-left:2px solid #EDEDED`. Legend (mono 11 `#A3A3A3`): "■ your lines · ▏woven context — slides in 250ms per line, your lines never move".
- **Approval card:** `width:264px; border:1px solid #EDEDED; border-radius:12px; padding:18px; gap:10px` — mono caps label ("CREATE EVENT" / "SAVE CONTACT" / "DRAFT EMAIL") → title 14px 500 → detail mono 12 `#525252` → buttons [Approve primary-small] [Edit ghost `#525252`] [Dismiss ghost `#A3A3A3`], `gap:4px`.
- **Approved chip:** `background:#0A0A0A; color:#FFFFFF; border-radius:999px; padding:8px 16px; 13px 500` — "✓ Event created" (approve-card motion end state).
- **Collapsed transcript bar:** full-width bottom, `border-top:1px solid #EDEDED; background:linear-gradient(#FFFFFF,#F7F7F7); padding:18px 64px` — "Transcript · 47 min · 6,204 words" mono 12 `#525252` | "expand ▾" mono 12 `#A3A3A3`.

## 06 · Ask Omni
- Column `width:720px`, canvas `padding:72px 0`, `gap:40px`.
- **Query input (filled):** `border:1px solid #0A0A0A; border-radius:12px; padding:16px 20px; 15px` + `↵` mono 11 `#A3A3A3` right.
- **Answer:** heading 20px Space Grotesk 600 −0.02em; prose 15px lh 1.8 ink with `<strong>` facts and inline citation markers `[1]` mono 12 `#A3A3A3`; sources block above `border-top:1px solid #EDEDED`, mono 12 `#525252`, hover `color:#0A0A0A` — "[1] vault/clients/northwind.md · renewal 2025-07-14".
- **Empty state:** centered; "Ask across everything you know" 40px SG 600 −0.03em; input ghost `border:1px solid #D4D4D4; color:#D4D4D4` + shortcut "Ctrl ⇧ A" mono 11, hover `border-color:#0A0A0A`; privacy line 13px `#A3A3A3`: "Answers come from your vault only. Nothing leaves this device."

## 07 · Dictation pill
- **Pill:** `border:1px solid #EDEDED; border-radius:999px; padding:10px 18px; gap:14px`, float shadow. Contents: waveform 110×18 (20 bars) · timer mono 12 · mode chip mono 11 caps.
- **Idle:** flat baseline (inactive wave), timer `00:00` `#A3A3A3`, mode "NOTE" `#D4D4D4`.
- **Listening:** live levels, timer + mode in ink.
- **Command parsed:** mode chip inverts — `background:#0A0A0A; color:#FFFFFF; border-radius:999px; padding:3px 10px` "COMMAND".
- **Approval popover:** `width:320px; margin-top:12px`, card radius 12 + float shadow, `padding:18px; gap:10px` — label "CREATE EVENT" → heard quote 13px italic `#A3A3A3` ("schedule lunch with dana friday noon") → title/detail/buttons identical to approval card. "popover rises 8px / 200ms".

## 08 · People
- Page `padding:48px 64px`; header title 28px + "38 contacts · built from your meetings" mono meta; search field `border:1px solid #D4D4D4; radius:8px; padding:9px 14px; 14px #A3A3A3; width:240px`.
- **Person card:** 3-col grid `gap:20px`; card `border:1px solid #EDEDED; radius:12px; padding:24px; gap:14px`, hover = float shadow. Name 20px SG 600; role 13px `#A3A3A3`; contact block mono 12 `#525252` over `border-top:1px solid #EDEDED`; missing data `#D4D4D4` ("no phone yet"); meetings section: label "MEETINGS · 4" + wiki-links mono 12 `#525252` hover ink — `[[2026-07-06 · Vendor call — Northwind]]`.

## 09 · Onboarding (4 × 560×560 cards, "a two-minute ritual")
1. **Welcome:** aperture-animated 120px mark, "Omni" 40px, blurb 14px `#525252` centered, [Begin] primary large, step marker "1 / 4" mono 11 `#A3A3A3`.
2. **Let Omni hear:** title 28px; permission rows `border:1px solid #EDEDED; radius:12px; padding:18px 20px` — Microphone: live meter (200×6) + granted chip `background:#0A0A0A; color:#FFF; radius:999px; padding:5px 14px; 12px 500` "✓ Granted"; System audio: empty track + [Grant] outline pill. Footnote: "No bot joins your calls. Audio is captured on this machine only."
3. **Choose your vault:** selected path row `border:1px solid #0A0A0A; radius:12px` with mono 13px `~/Documents/vault` + Change ghost; tree preview mono 12 `#A3A3A3`; [Use this folder] primary.
4. **Models:** key row `border:1px solid #EDEDED; radius:12px` mono 13 `#525252` masked key `sk-ant-••••••••••••R2Qw` + "✓ Valid" 12px 500 ink; download rows: mono 12 name/size/status + progress bar `height:4px` track `#EDEDED` fill `#0A0A0A` radius 999 (done = full black bar; queued = `#A3A3A3` text). [Finish] disabled until done. Footnote: "Transcription runs on this device. Cloud models are optional and per-task."

## 10 · Settings (router + ledger)
- Page `padding:48px 64px 56px`; two-column grid `gap:48px`; sections labeled mono 11 caps `#A3A3A3`.
- **Settings group card:** `border:1px solid #EDEDED; radius:12px; padding:6px 20px`; rows `padding:14px 0; border-bottom:1px solid #EDEDED` (last row none) — label 14px | value mono 12 `#525252` with `▾` dropdowns; two-line rows add sub-caption 12px `#A3A3A3`; toggles right.
- **Keycaps** (hotkey): `border:1px solid #D4D4D4; radius:6px; padding:3px 8px; mono 12; box-shadow:0 1px 0 #D4D4D4` — Ctrl ⇧ Space + "Record" 13px `#525252`.
- **Router matrix:** card `padding:20px`, mono 12. Header row `grid 1.4fr 1fr 1fr 1fr; border-bottom:1px solid #0A0A0A` caps 11. Radio: selected `10px dot background:#0A0A0A; radius:50%`; unselected `border:1px solid #D4D4D4`. Rows: transcription, note enhancement, live answers, action parsing, embeddings.
- **Cost + latency ledger (last 30 days):** `grid 1.4fr .8fr 1fr .8fr .8fr` — task/calls/tokens/p50/cost, right-aligned numerics, total row `font-weight:500`. Sample: "note enhancement · 92 · 1.21M · 3.8s · $4.12"; total "374 · 1.57M · — · $5.99".

## 11 · Tray + toast
- **Tray menu:** `width:280px; radius:12px; border:#EDEDED; float shadow; padding:8px`. Status header `padding:12px 14px; border-bottom:1px solid #EDEDED`: breathing ring + "Capturing" 13px 500 + "Vendor call — Northwind · 00:12:04" mono 11 `#A3A3A3`. Items `padding:10px 14px; 14px; radius:8px` hover `#F7F7F7`; shortcut hints mono 11 right; Quit separated by `border-top`, `#525252`.
- **Capture toast:** `width:360px; radius:12px; float shadow; padding:20px; gap:12px` — "Teams call detected" 14px 500 + source 13px `#A3A3A3` → [Start capturing primary-small] [Not now ghost] → "auto-dismisses in 30s · never auto-starts" mono 11. Position: "bottom-right, rises 8px / 200ms".

## 12 · Mobile companion (future scope, 390×844 iOS frame)
Same language at phone scale: home (Today list + 84px black record button with 22px white ring), recording (breathing ring 16px + mono 32px timer + wave 220×36 + "Transcribing on your desktop over local Wi-Fi." + Stop outline pill), synced note (same enhance + approve components). Mode chips Idea/Meeting = inverted/outline pills.

## 13 · Connections
- Intro: title 28px + "Omni reads to give context and drafts on your behalf. It never sends or changes anything without an approval." 14px `#525252`.
- **Service rows** (in group card, `padding:16px 0`): name 14px 500 + scope mono 11 `#A3A3A3` ("read + draft only, never sends") | right: "✓ Connected" 12px 500 + Disconnect ghost `#A3A3A3`, or [Connect] outline pill.
- **Paired devices card:** breathing ring on "This PC — DESKTOP-7F2K · the brain · models + vault live here"; phone row "local Wi-Fi sync · end-to-end encrypted · last seen 2 min ago" + "✓ Paired".
- **Pairing code:** mono 24px `letter-spacing:0.15em; border:1px solid #0A0A0A; radius:8px; padding:10px 20px` — "7F2K-93QX" + "expires in 09:41" mono 11.
- Trust footnote 12px `#A3A3A3`: "Tokens are stored encrypted on this device. Every write goes through an approval card first."
