# Naomi Research Library

Research feeding the Naomi realtime voice agent: the "black pool of water" visual (Track A)
and the millisecond-feel voice pipeline (Track B). One folder per source/technique family,
each with a faithful `summary.md` (exact citations) and a `best-parts-to-take.md`.

The build contract distilled from this library lives at `docs/design/naomi-visual-brief.md`.

## Track A — the art

| Folder | Source | Why it matters |
| --- | --- | --- |
| `stam-1999-stable-fluids/` | Stam, SIGGRAPH 99 | The canonical real-time Navier-Stokes solver; defines the "true simulation" branch |
| `harris-2004-gpu-gems-38-fast-fluid-dynamics/` | Harris, GPU Gems ch. 38 | Canonical GPU/fragment-shader implementation of Stam's method |
| `dobryakov-webgl-fluid-simulation/` | PavelDoGreat repo | Best-known browser implementation; the visual/cost reference point |
| `bridson-2007-curl-noise/` | Bridson et al., SIGGRAPH 2007 | Stateless divergence-free flow — the core of the chosen technique |
| `quilez-smooth-minimum-sdf-blending/` | Quilez, iquilezles.org | Exact smin formulas for liquid surface-tension blending |
| `webview2-rendering-capabilities/` | Tauri + Microsoft Learn | What the shell can actually run: WebGL2 yes, WebGPU no bet |
| `voice-orb-prior-art/` | Siri / ChatGPT orb / Apple Intelligence | What makes assistant visuals feel alive vs gimmicky |
| `russell-1980-circumplex-model-of-affect/` | Russell, JPSP 1980 | The valence/arousal model behind the emotion→physics map |

## Track B — the voice pipeline

| Folder | Source | Why it matters |
| --- | --- | --- |
| `cartesia-sonic-realtime-tts/` | Cartesia docs + sonic page | Exact WS API, models, PCM formats, emotion controls, cancel semantics |
| `voice-agent-latency-and-barge-in/` | Industry engineering sources | Where each millisecond goes; barge-in discipline |
