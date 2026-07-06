# Best parts to take — Russell (1980) circumplex

1. **The affect contract is `(valence, arousal, burst)`:** valence ∈ [−1, 1], arousal ∈
   [0, 1], burst = optional laugh event with intensity. Every producer (LLM self-tag,
   prosody fallback) and every consumer (shader uniforms, Cartesia controls) speaks only
   this triple — one typed contract between engine and UI.
2. **Axis→physics assignment with a principled rationale:** arousal (activation) drives
   *energy* parameters — flow speed, noise frequency, attack sharpness; valence
   (pleasure) drives *shape* parameters — roundness/surface tension (smin k), buoyancy
   (vertical rest offset). Agitated and happy can share arousal yet look different because
   valence splits them — exactly the circumplex's quadrant structure.
3. **Nearest-region quantization to Cartesia's enum:** map (v,a) quadrants to
   `content/calm/neutral/angry/sad`; keeps voice and visual affect provably consistent
   because both derive from the same triple.
4. **Smoothing:** ease (v,a) with ~600ms critically-damped smoothing before applying —
   affect is a mood, not a per-word flicker (matches the psychology: core affect drifts).
