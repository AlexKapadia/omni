# Best parts to take — Cartesia Sonic WebSocket TTS

1. **Pin the model:** ship with `sonic-3.5-2026-05-04` (pinned snapshot) in config, not
   `sonic-latest` — deterministic voice across updates; upgrade deliberately.
2. **`pcm_f32le` @ 24000 Hz raw container** — Float32Array chunks feed an AudioWorklet
   ring buffer with no decode step and no resample if the AudioContext is created with
   `sampleRate: 24000`. Lowest possible playout latency.
3. **Sentence-streaming with `continue: true`:** send the LLM's text as it streams
   (clause-sized chunks on punctuation), same `context_id`; `continue: false` on stream
   end. First audio starts while the LLM is still writing the second sentence.
4. **`cancel: true` is the barge-in primitive** — one frame to send; pair with a local
   gain ramp (~20ms) so playback dies instantly even before the server acks.
5. **One affect source, two sinks:** the engine's (valence, arousal) triple quantizes to
   `generation_config.emotion` (`content`/`calm`/`neutral`/`angry`/`sad`) and modulates
   `speed` (0.9 calm → 1.15 excited); the same triple goes to the visual. Laugh bursts ride
   inline `[laughter]` tags in the transcript.
6. **`add_timestamps: true` always** — word timings drive caption highlight and give the
   visual a phoneme/word-rate pulse train that pure FFT can't provide as cleanly.
7. **Keys stay in the engine** (X-API-Key header server-side; never the browser
   `access_token` path) — upholds the "UI process never holds keys" invariant (§5.6).
