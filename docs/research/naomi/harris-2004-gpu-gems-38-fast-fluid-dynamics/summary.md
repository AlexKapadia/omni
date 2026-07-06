# Fast Fluid Dynamics Simulation on the GPU — Mark J. Harris (GPU Gems ch. 38, 2004)

**Citation:** Harris, Mark J. "Chapter 38. Fast Fluid Dynamics Simulation on the GPU."
In *GPU Gems: Programming Techniques, Tips, and Tricks for Real-Time Graphics*,
ed. Randima Fernando. NVIDIA / Addison-Wesley, 2004.
**Link:** https://developer.nvidia.com/gpugems/gpugems/part-vi-beyond-triangles/chapter-38-fast-fluid-dynamics-simulation-gpu
**Fetched:** 2026-07-06 (NVIDIA Developer online edition).

## What it is

The canonical translation of Stam's Stable Fluids (1999) to fragment shaders: fields stored
as floating-point textures, one full-screen pass per solver stage, per timestep:

1. **Advection (semi-Lagrangian):** "trace the trajectory of the particle from each grid cell
   back in time" — `q(x, t+dt) = q(x − u(x,t)·dt, t)`; unconditionally stable regardless of dt.
2. **Viscous diffusion:** implicit `(I − ν·dt·∇²)u = u_advected` via Jacobi iteration
   (~20-50 iterations for acceptable convergence).
3. **Pressure projection:** divergence of intermediate velocity → Poisson pressure equation
   `∇²p = −∇·u_intermediate` via ~40-80 Jacobi iterations → subtract ∇p to enforce
   incompressibility.
4. **Force application:** external accelerations added as Gaussian spatial impulses.

Grid guidance: interactive results at 128×128 to 512×512 2D texture grids; velocity and
pressure in float textures, passive scalars (dye/density) in separate channels. Extensions:
vorticity confinement, 3D via tiled flat textures, staggered grids, arbitrary boundaries.

## Cost analysis for Naomi (WebView2 / integrated GPU)

Per frame: 1 advect + ~20-50 diffusion Jacobi + divergence + ~40-80 pressure Jacobi +
gradient-subtract + dye advect ≈ **70-130 full-screen FBO passes** over persistent
half-float textures (WebGL2: requires `EXT_color_buffer_float` for render-to-float).
Pass count, not pixel shading, dominates on integrated GPUs. Real fluid state is also
non-deterministic across resize/restore and cannot be trivially frozen for
prefers-reduced-motion.
