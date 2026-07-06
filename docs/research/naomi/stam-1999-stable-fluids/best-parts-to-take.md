# Best parts to take — Stable Fluids (Stam 1999)

1. **The stability argument, not the solver.** Semi-Lagrangian sampling (`value at x = value
   at x − u·Δt`) is bounded by construction. Naomi's shader reuses exactly this idea as
   *domain warping*: sample noise at a back-advected coordinate. We get the fluid look with
   zero simulation state.
2. **Numerical dissipation is a feature here.** Stam concedes his flow "dampens too rapidly";
   for a calm idle pool that damping *is the aesthetic* — motion decays to stillness unless
   speech keeps injecting energy. We replicate it as an envelope decay constant, not a PDE.
3. **Force injection model.** Forces enter as `w1 = w0 + Δt·f` at the start of each step —
   the pattern for mapping audio energy into the visual: speech = time-varying `f`.
4. **What we deliberately do NOT take:** the Poisson projection / linear solves. Multi-pass
   FBO ping-pong per frame is the single biggest GPU cost and fragility (half-float
   attachment support) on integrated GPUs inside WebView2. Bridson's curl-noise gives
   divergence-free motion in closed form instead.
