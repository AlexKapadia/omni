# Best parts to take — latency budgets & barge-in

1. **Budget from end-of-speech, headline target p50 ≤ 650ms / p95 ≤ 1000ms** to first
   audible audio. Instrument every stage (Omni already has
   `engine/stt/transcription_latency_tracker.py` as the pattern to extend).
2. **Stream at every seam:** Parakeet partials are already streaming (local); fire the
   router request on VAD end-of-speech using the *partial-final* transcript; stream LLM
   tokens; dispatch TTS per clause (first punctuation or ~12 tokens); play PCM chunks as
   they arrive. No stage waits for a predecessor to finish.
3. **Tune Silero end-pointing to ~200ms min-silence** for Naomi turns (more aggressive
   than meeting transcription; it's a config profile, not a code fork) — recover from
   false end-points by continuing the same LLM context.
4. **Barge-in protocol (exact order):** VAD speech-onset (2 consecutive frames) →
   (a) AudioWorklet gain ramp to 0 over 20ms, flush ring buffer; (b) Cartesia
   `{"context_id", "cancel": true}`; (c) abort Groq HTTP stream; (d) visual state →
   `listening` with a single inward "swallow" deformation. Perceived stop < 50ms.
5. **Debounce against false barge-ins:** require ~60-100ms of sustained mic speech;
   never trigger from loopback; brief overlap is preferable to cutting Naomi off wrongly.
6. **Latency is a tested contract:** each budget line becomes an assertion with a synthetic
   fixture (fake provider clocks) + a real-world validation pass on public audio (§3.12).
