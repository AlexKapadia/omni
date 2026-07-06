# Best parts to take — Quilez smooth minimum

1. **Quadratic smin as the default** — cheapest branch-free form, C1 continuity is enough
   for a filled 2D pool (we shade from the SDF value/gradient, not raytraced normals).
2. **k in real distance units.** Because Quilez's rewrite normalizes k to the blend
   thickness, the emotion table can specify surface tension in fractions of pool radius
   (e.g. `k = 0.25R` calm → `0.06R` agitated) and the visual result is predictable —
   no magic constants.
3. **Exponential smin for n-ary blends** — when laughter spawns 2–4 satellite droplets,
   the order-independent exponential form blends main pool + all droplets symmetrically.
4. **SDF-first architecture:** define the whole Naomi form as one scalar field
   `d(p) = smin(pool, droplets..., k)`; the fill, the rim line, the interior shading bands and
   the curl-noise boundary ramp (Bridson d(x)) all read the *same* field — one source of
   truth, no seams between systems.
