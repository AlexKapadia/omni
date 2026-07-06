# Best parts to take — voice-orb prior art

1. **Asymmetric dynamics everywhere.** Reuse Omni's own waveform constants as the house
   physicality signature: attack `lv += (target − lv) · 0.5`, decay `lv · 0.93` per frame —
   applied to every audio-driven visual parameter, not just size.
2. **Multi-band → multi-behavior mapping:** phrase energy → pool swell; syllable-rate flux
   → rim ripples; high-band energy → fine surface texture. Never one scalar → one scale.
3. **Idle breathing synchronized to the product heartbeat:** the pool's resting swell uses
   the existing `--dur-breathe: 2400ms` sine — Naomi and the capture ring breathe together;
   the brand ring at 8px and the pool at 480px are the same organism.
4. **Continuous identity:** all states (idle/listening/thinking/speaking/laughing/agitated)
   are parameter regions of one SDF form with eased transitions (300–600ms), never a
   component swap.
5. **Peripheral restraint:** emotion shows in the pool's *motion quality*, not in size
   explosions; max radius excursion ±8% except laughter pulses (+10% peaks).
