# Best parts to take — GPU Gems ch. 38 (Harris 2004)

1. **The cost ledger.** 70–130 full-screen passes/frame with Jacobi iteration is the honest
   price of a true grid solver — the number that disqualifies it as Naomi's *primary*
   technique on integrated GPUs, and the benchmark any alternative must beat.
2. **Texture-as-field thinking.** If a later Naomi iteration wants persistent ink trails
   (speech leaves a wake that keeps swirling), Harris's advection pass alone — one ping-pong
   pass, skipping diffusion/projection, with curl-noise as the velocity field — is the
   cheapest upgrade path. Advecting a dye texture through Bridson curl-noise needs **no**
   Poisson solve because curl-noise is already divergence-free.
3. **Gaussian impulse splats** for force injection — the right shape for "a word just landed
   in the pool" ripples if we ever add positional impulses.
4. **Capability gate:** render-to-float needs `EXT_color_buffer_float` in WebGL2 — a
   runtime check the fallback ladder must perform before enabling any texture-state tier.
