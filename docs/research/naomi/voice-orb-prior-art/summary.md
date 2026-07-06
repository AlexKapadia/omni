# Voice-assistant visual prior art — Siri, ChatGPT orb, Apple Intelligence, JARVIS genre

**Sources surveyed 2026-07-06 (patterns and principles only — no pixels, no brand identity):**
- OpenAI. "Voice Mode FAQ." OpenAI Help Center. https://help.openai.com/en/articles/8400625-voice-mode-faq
  — plus reporting on the orb-to-integrated transition (webpronews.com "The Death of the
  Overlay", 2026; PCMag coverage): the classic Advanced Voice Mode presented a full-screen
  breathing orb whose fluid blue/white motion morphed with conversation state.
- Craig Dehner (Apple motion designer). "Siri" case study. https://craigdehner.com/siri/ —
  the iOS Siri waveform's design intent.
- kopiro/siriwave — "The Apple Siri wave-form replicated in a JS library."
  https://github.com/kopiro/siriwave — documents the genre's math: summed damped sinusoids,
  amplitude driven by speech level.
- jacobamobin/AppleIntelligenceGlowEffect (2024) https://github.com/jacobamobin/AppleIntelligenceGlowEffect
  and WWDC26 "Siri glow" reporting (AppleMagazine, 2026) — the edge-glow state language:
  ambient, screen-peripheral, state-not-content.
- constzz/Animated-Voice-Blob — Telegram-style voice blob (iOS), two overlapping
  noise-displaced blobs scaled by audio level. https://github.com/constzz/Animated-Voice-Blob
- Omni's own design brief §8 (docs/design/design-brief.md) — the in-house waveform:
  "driven by real levels · fast attack (0.5), damped decay (0.93) so it feels physical".

## Distilled principles — what makes these feel ALIVE

1. **Idle is never dead.** Every credible assistant visual breathes at rest (Siri orb slow
   swell, ChatGPT orb drift). Liveness = low-amplitude autonomous motion, not zero motion.
2. **Physicality beats literalism.** Siri's waveform and Omni's own meter feel "physical"
   because of asymmetric dynamics — fast attack, slow damped decay. Instant 1:1 mapping of
   level→size reads as a VU meter (gimmick); inertia reads as a body being moved.
3. **State changes are material changes, not color changes.** The ChatGPT orb morphs
   shape/motion between listening/thinking/speaking. For monochrome Omni this is the only
   available language anyway — brief: "State is weight, scale, motion and depth — never hue."
4. **Reactivity must be multi-band.** Blobs driven by a single RMS scalar pulse like a
   speaker cone (gimmick signature). Alive versions decompose the signal (bands,
   syllable-rate pulses vs phrase-level energy) into *different* physical responses.
5. **Restraint at the edges.** Apple's glow works because it stays peripheral and calm;
   over-animated assistants read as anxious. Idle amplitude should be barely perceptible.
6. **One form, continuous identity.** The character is a single persistent body that
   transforms — never swapped icons/spinners. Interruptions deform it; they don't reset it.

## Gimmick signatures to ban

- Raw per-frame FFT bars / level-scaled circle (VU-meter feel).
- Symmetric attack/decay (no inertia).
- Looping canned animation that ignores the actual audio.
- Chromatic emotional coding (violates Omni monochrome absolutism).
- Motion that never rests (idle should approach stillness, per reduced-motion ethos).
