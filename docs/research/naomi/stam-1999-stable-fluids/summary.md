# Stable Fluids — Jos Stam (SIGGRAPH 1999)

**Citation:** Stam, Jos. "Stable Fluids." *SIGGRAPH 99 Conference Proceedings*, Los Angeles, CA, August 1999, pp. 121-128. ACM. Copyright ACM 1999 0-201-48560-5/99/08.
**Link:** https://pages.cs.wisc.edu/~chaol/data/cs777/stam-stable_fluids.pdf (author page: https://www.josstam.com/publications)
**Read:** full paper read verbatim (8 pages) on 2026-07-06.

## Claim (verbatim)

> "In this paper, for the first time, we propose an unconditionally stable model which still produces complex fluid-like flows."

Stam solves the incompressible Navier-Stokes equations:

- Mass conservation (Eq. 1): `∇ · u = 0`
- Momentum (Eq. 2): `∂u/∂t = −(u·∇)u − (1/ρ)∇p + ν∇²u + f`

where `ν` is kinematic viscosity, `ρ` density, `f` external force.

## Method — four-step operator splitting

Using the Helmholtz-Hodge decomposition (`w = u + ∇q`, Eq. 3) he defines a projection
operator **P** onto divergence-free fields via a Poisson equation `∇·w = ∇²q` (Eq. 4),
yielding the fundamental equation (Eq. 5): `∂u/∂t = P(−(u·∇)u + ν∇²u + f)`.

Each timestep Δt resolves the terms sequentially:

```
w0(x) --add force--> w1(x) --advect--> w2(x) --diffuse--> w3(x) --project--> w4(x)
```

1. **Add force:** `w1(x) = w0(x) + Δt f(x, t)`.
2. **Advect (semi-Lagrangian, method of characteristics):** `w2(x) = w1(p(x, −Δt))` —
   backtrace each point through the velocity field; "the maximum value of the new field is
   never larger than the largest value of the previous field", hence *unconditionally stable*
   ("No matter how big the time step is, our simulations will never 'blow up'").
3. **Diffuse (implicit):** `(I − νΔt∇²) w3(x) = w2(x)` — a sparse linear system.
4. **Project:** solve `∇²q = ∇·w3`, then `w4 = w3 − ∇q`. "The projection step forces the
   fields to have vortices which result in more swirling-like motions."

Complexity O(N) with a multigrid solver. Known limitation (author's own words): it
"suffers from too much 'numerical dissipation', i.e., the flow tends to dampen too rapidly" —
acceptable in interactive systems where forces keep the flow alive.

## Relevance to Naomi

This is the honest physics branch: a real velocity field a voice could stir. Visual character:
ink/smoke swirls filling the domain — *dye in water* rather than *a bounded pool of water*.
Requires per-frame multi-pass solves (advect, diffuse, project) over persistent state textures.
