# Best parts to take — Dobryakov WebGL-Fluid-Simulation

1. **Decoupled sim/render resolution** — generalized into Naomi's `renderScale` knob:
   shade at 0.5–0.75× device pixels, upscale with the GPU's free bilinear filter. Liquid
   has no hard texture detail, so upscaling is visually free.
2. **Motion qualities to reproduce procedurally:** momentum (motion outlives the
   impulse), advection lag (energy travels through the surface, not everywhere at once),
   and persistent swirl. In the chosen stateless design these come from envelope
   attack/decay asymmetry and time-flowing curl noise rather than stored velocity.
3. **Config surface as UX:** dissipation/curl/pressure exposed as few named floats is the
   right shape for the emotion→physics parameter block — a single uniform struct.
4. **Extension-probing ladder** (half-float → float fallbacks) — copy the *discipline*: probe
   `EXT_color_buffer_float` and friends at boot, choose tier, never assume.
5. **What not to take:** bloom/sunrays post-chain (chromatic, off-brand for monochrome
   Omni) and screen-filling dye (Naomi is a bounded form on a white canvas).
