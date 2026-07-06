# Best parts to take — Curl-Noise (Bridson et al. 2007)

1. **2D stream-function form** `v = (∂ψ/∂y, −∂ψ/∂x)` — two cheap noise gradient
   evaluations per sample; exactly incompressible, so the interior of the pool reads as
   liquid, not as scrolling noise. This is Naomi's core motion field.
2. **The rim ramp (Eq. 3 + quintic ramp Eq. 4).** `ψ_constrained = ramp(d/d0)·ψ` with the
   pool's own SDF as d(x): flow is tangent at the boundary, so motion hugs and swirls along
   the rim instead of leaking out. d0 tied to noise scale L, exactly as the paper advises.
3. **Modulate the potential, never the velocity** — emotion-driven amplitude fields A(x)
   (e.g. more turbulence near the rim when agitated) stay divergence-free via
   `v = ∇×(Aψ)`.
4. **Octave scaling law** (vortex diameter ≈ L, speed ≈ O(1/L)) — gives a principled
   emotion knob: agitation raises noise frequency (smaller, faster vortices); calm lowers it
   (large slow swells). Not arbitrary tuning — the paper's own scale analysis.
5. **Time-varying noise** for evolution: `ψ(x, t)` with t as a shader uniform — freezing t is
   the exact reduced-motion behaviour ("freeze all loops, keep end states").
