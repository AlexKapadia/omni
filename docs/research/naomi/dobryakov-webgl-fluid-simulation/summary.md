# WebGL-Fluid-Simulation — Pavel Dobryakov (PavelDoGreat)

**Citation:** Dobryakov, Pavel. "WebGL-Fluid-Simulation — Play with fluids in your browser
(works even on mobile)." GitHub repository, MIT license, first released 2017, actively
forked/adapted since.
**Links:** https://github.com/PavelDoGreat/WebGL-Fluid-Simulation · live demo: https://paveldogreat.github.io/WebGL-Fluid-Simulation/
**Surveyed:** 2026-07-06 (repo, demo, derivative implementations).

## What it is

The best-known browser GPU Navier-Stokes solver — a single-file WebGL implementation of
the Stam/Harris pipeline (advection, pressure projection via Jacobi iteration, vorticity
confinement) with dye rendering, bloom and sunrays post-effects. Runs on WebGL1 with
extensions or WebGL2; famously runs "even on mobile" by decoupling resolutions.

## Implementation facts relevant to Naomi

- **Decoupled resolutions:** physics grid (default `SIM_RESOLUTION: 128`) vs dye/render
  resolution (default `DYE_RESOLUTION: 1024`) — the key trick that makes a true solver
  interactive on weak GPUs.
- Configurable dissipation (`DENSITY_DISSIPATION`, `VELOCITY_DISSIPATION`) controls how
  fast dye and motion fade — the "viscosity feel" knobs.
- Vorticity confinement (`CURL`) re-injects small-scale swirl lost to numerical dissipation.
- Uses half-float textures; probes and falls back across `OES_texture_half_float` /
  `EXT_color_buffer_float` variants — evidence that float-buffer support is the fragile
  point across GPUs/drivers.
- Performance reality: smooth on discrete GPUs; on weak/integrated GPUs it is playable
  only by lowering `SIM_RESOLUTION`/`DYE_RESOLUTION` — community forks exist
  specifically to tone it down for use as a background (e.g. tkabalin/WebGL-Fluid-Background).

## Visual character verdict for Naomi

Splendid as *colored dye bursts filling the screen*; as a strict-monochrome bounded "pool of
black water" it fights us: the sim wants to fill its domain, dye diffuses into grey mud rather
than staying ink-black, and confining it to a blob shape requires boundary masks that
undercut the free-flow beauty that is its whole point. It is the reference for what "real
fluid" motion *feels* like — advection lag, momentum, swirls that keep evolving after the
impulse stops — qualities the chosen technique must reproduce.
