# Omni — real-product showcase media

Every asset here is the **real Omni app running end-to-end against the real
Python engine** — never mock mode, never a generated/painted mock-up. The demo
video is **genuinely screen-recorded** by Playwright (`recordVideo`) while a
script drives the running app; it is not AI-generated.

## How it was captured (honest boundary)

- **Real engine.** A real `python -m engine.server` sidecar was booted on a
  temp SQLite DB seeded with synthetic (non-PII) meetings and a small Obsidian
  vault, indexed by the real BM25/`bge-small` indexer. Provider keys came from
  the local `.env` (never printed or committed).
- **Real data flow.** Ask answers are produced by the real retrieval + router
  pipeline: BM25 over the indexed vault → **Google Gemini** synthesis
  (`gemini-2.5-flash` → `gemini-2.5-pro` fallback). The router matrix, cost
  ledger, device list, and meeting content are all read live from the engine.
- **The one shim.** The UI normally runs inside a Tauri 2 desktop shell. These
  captures run the **production web build in headless Chromium** with a thin
  test shim that stubs *only* the OS-native Tauri seams (the folder picker,
  tray/window handles) so the React app mounts. **All data-bearing traffic
  still goes to the real engine over the real localhost WebSocket** — nothing
  about the product's behaviour is faked. Because it is the web build, native
  OS chrome (the Tauri title bar / tray) is not shown.
- **Not shown / honest gaps.** A *live flowing* transcript is not captured:
  that requires real WASAPI/mic audio and loaded STT models, and this harness
  deliberately never records the user's real audio. Real transcript segments
  are instead shown in the meeting-detail pane (`02-meeting-detail.png`), read
  from the engine. Naomi's pool renders its real idle WebGL water (60 fps); her
  voice/affect is not driven here.

## Assets

| File | What it shows (all real) |
| --- | --- |
| `omni-demo.mp4` / `omni-demo.gif` | ~10 s recorded tour: Library → meeting detail → a real Gemini-answered Ask with citations → Settings (router + ledger) → Naomi. |
| `screenshots/01-library.png` | Library home — real seeded meetings grouped by day, live engine heartbeat in the footer. |
| `screenshots/02-meeting-detail.png` | Meeting detail — real enhanced notes, honest "Nothing to approve", verbatim user notes, real transcript segments. |
| `screenshots/03-ask-answer.png` | Ask Omni — real synthesized answer with inline superscript citations, exact source chips (note path + line range), engine-measured latency. |
| `screenshots/04-settings-router.png` | Settings — real device enumeration, F9 hotkey, and the real AI router matrix (Groq / Gemini fallback chains, per-task budgets). |
| `screenshots/05-settings-ledger-keys.png` | Settings — real privacy toggles, deny-by-default instant-execute, real cost+latency ledger, DPAPI-masked keys. |
| `screenshots/06-naomi-pool.png` | Naomi — the real living-water pool (WebGL, tier 3 · 60 fps) with the conversation + tuning panels. |
| `screenshots/07-onboarding-welcome.png` … `10-onboarding-models.png` | The genuine first-run wizard's four steps (welcome → vault → keys → models + the honest Finish gate). |

Screenshots are captured at the 1440×900 design canvas at 2× (2880×1800) for
crisp framing.
