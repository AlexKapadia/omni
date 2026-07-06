# Cartesia Sonic realtime TTS — WebSocket streaming API

**Primary sources (fetched 2026-07-06):**
- Cartesia. "Text-to-Speech (WebSocket)." API reference. https://docs.cartesia.ai/api-reference/tts/websocket
- Cartesia. "Models — TTS." https://docs.cartesia.ai/build-with-cartesia/models/tts
- Cartesia. "Sonic" product page. https://www.cartesia.ai/sonic/
- Cartesia Python SDK: https://pypi.org/project/cartesia/

**Secrets discipline:** API key/voice referenced ONLY as env vars `CARTESIA_API_KEY` and
`CARTESIA_VOICE_ID` (already in `.env`, DPAPI-managed at onboarding per §5.6). Never read,
printed, or logged.

## Endpoint & auth

- `wss://api.cartesia.ai/tts/websocket`, required query param `cartesia_version`
  (e.g. `2026-03-01`).
- Auth: `X-API-Key` header (server-side — the engine holds keys, never the UI) or
  `access_token` query param (client-side use; NOT used in Omni — UI process never holds keys).

## Models

- `sonic-3.5` (stable, auto-updated) / pinned snapshot `sonic-3.5-2026-05-04` (production
  recommendation) / `sonic-3` / `sonic-latest` (beta only).
- Latency: Cartesia claims **sub-90ms** model latency for Sonic (sonic product page);
  third-party engineering write-ups measure ~40ms time-to-first-byte for the fastest
  Sonic tier and <100ms for standard (inworld.ai and getstream.io benchmarks, 2026) —
  treat vendor numbers as marketing until measured in-app; budget conservatively at
  40-90ms TTFA + network RTT.
- 42 languages; "interprets the emotional subtext in the transcript and calibrates
  delivery automatically"; inline non-verbal tags demonstrated on the product page, e.g.
  `"I can't believe we actually made it. [laughter] Finally!"`.

## Request schema (exact field names)

Required: `model_id`, `transcript`, `context_id` (generation session), `voice`
(`{"mode": "id", "id": "<CARTESIA_VOICE_ID>"}`), `output_format`.

- `output_format`: `container: "raw"`, `encoding`: `pcm_f32le` | `pcm_s16le` | `pcm_mulaw`
  | `pcm_alaw`; `sample_rate`: 8000 | 16000 | 22050 | 24000 | 44100 | 48000 Hz.
  For browser playback: `pcm_f32le` @ 24000 or 44100 → zero-conversion feed into Web Audio.
- **Continuations:** `continue: true` while more transcript chunks follow on the same
  `context_id`; `false` on the final chunk ("Set to false on the last transcript chunk for
  this context to minimize latency"). `flush` forces immediate processing and returns a
  `flush_id`.
- **Cancellation (barge-in primitive):** `{"context_id": "...", "cancel": true}` stops
  generation for that context.
- **Speech controls** `generation_config`: `volume` 0.5-2.0x, `speed` 0.6-1.5x,
  `emotion`: `neutral` | `calm` | `angry` | `content` | `sad`.
- **Timestamps:** `add_timestamps` (word-level start/end arrays, seconds);
  `add_phoneme_timestamps` (phoneme-level). Word timestamps let the UI know exactly which
  word is sounding — usable for visual syllable pulses and live caption alignment.
- WebSocket **multiplexing**: multiple concurrent generations over one socket,
  distinguished by `context_id`.
