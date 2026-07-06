# Naomi Visual Brief — THE BUILD CONTRACT

**Status:** ratified research deliverable, 2026-07-06. Evidence: `docs/research/naomi/**`
(10 sourced folders). Build agents implement from THIS file without re-research.
**Owner's vision (verbatim intent):** *"a black sort of pool of water... it's moving around,
and it reacts to what you're saying... you could tell when it's laughing, when it's happy,
when it's agitated... like a floating pool of water that moves and flows really nicely as
you're talking."* NOT a plain white screen.
**Design-system law (docs/design/design-brief.md):** white canvas, black and grey only;
"State is weight, scale, motion and depth — never hue." Naomi must feel native to Omni yet
transcendent.

---

## 1. Chosen technique — and why it wins

**WINNER: a single-pass WebGL2 fragment shader rendering a 2D signed-distance-field
"pool" — an ink-black SDF blob whose rim is displaced by FBM noise, whose interior
flows by Bridson curl-noise advection (divergence-free, rim-tangent), with liquid
surface-tension behaviour from Quilez smooth-minimum blending of the main pool with
transient satellite droplets. Stateless: every frame is a pure function of
(time, audioFeatures, affect). No FBOs, no float render targets, no simulation memory.**

### The candidates, measured against the same criteria

| Criterion | A. GPU Navier-Stokes (Stam/Harris/Dobryakov) | B. Raymarched 3D metaballs (Quilez/Codrops) | **C. 2D SDF pool + curl-noise + smin (CHOSEN — a hybrid of B's SDF language and A's fluid motion, per §3.5 "prefer hybrids")** |
| --- | --- | --- | --- |
| Reads as "pool of black water" | No — dye/smoke filling the screen; confining to a blob fights the sim | Partly — reads as a 3D droplet/orb; heavier "object" than "pool" | **Yes — a bounded liquid surface with internal circulation and a living rim** |
| GPU cost (integrated, WebView2) | 70–130 full-screen FBO passes/frame (Harris ch.38) + float-buffer fragility | 64–128 raymarch steps × noise evals per pixel | **1 pass, ~4–6 noise evals/pixel; renderScale-degradable** |
| WebGL2-only, no extensions | ✗ needs `EXT_color_buffer_float` ping-pong | ✓ | **✓ (not even derivatives needed)** |
| Emotion controllability | Indirect (forces in, look emerges) | Good | **Direct: every physical quality is a closed-form uniform** |
| Deterministic / testable / freezable | ✗ stateful | ✓ | **✓ pure function of (t, audio, affect) — golden-frame testable, reduced-motion = freeze t** |
| Monochrome discipline | Dye greys go muddy | Lighting wants speculars/color | **Shading = quantized grey bands from the SDF — native to the brief** |

Evidence trail: cost ledger in `harris-2004-gpu-gems-38-fast-fluid-dynamics/`; motion-quality
bar in `dobryakov-webgl-fluid-simulation/`; incompressible bounded flow in
`bridson-2007-curl-noise/` (v = ∇×ψ, ψ ramped to zero at the rim ⇒ flow provably tangent
to the pool edge — the water circulates *inside its own boundary*, which is precisely the
"pool" read); surface tension in `quilez-smooth-minimum-sdf-blending/`; shell constraints in
`webview2-rendering-capabilities/` (Microsoft: production apps must not rely on browser
flags ⇒ WebGPU is not a target); aliveness principles in `voice-orb-prior-art/`.

### Fallback ladder (probe at boot, never assume)

1. **Tier 1 — WebGL2** single-pass shader (primary; every non-blocklisted WebView2).
2. **Tier 2 — WebGL1** same shader as GLSL ES 1.00 (only if webgl2 context creation fails).
3. **Tier 3 — Canvas2D** analytic pool: rim = radius + 3 summed harmonics + envelope;
   interior = 3 layered radial gradients in brief greys; ≤2ms/frame. Also auto-selected
   when `WEBGL_debug_renderer_info` reports SwiftShader (software GL).
4. **Tier 4 — static frame** of Tier 3 (reduced-motion base state; also the zero-GPU path).

Every tier renders the same design language and all states. No spinners, no blank panels.

### Shader architecture (Tier 1 spec)

One full-screen triangle; fragment shader in pool-local coordinates `p` (pool radius R = 1):

1. **Form:** `d(p) = smin( sdCircle(p − c₀, r₀·breath), sdCircle(p − cᵢ, rᵢ)..., k )` —
   main pool + 0–4 satellite droplets (positions on slow orbits, spawned by burst events).
   Quilez quadratic smin; k = surface tension (emotion-driven). Droplet count/positions are
   deterministic functions of (t, burstSeed).
2. **Rim displacement:** `d ← d + fbm(θ·fᵣ, t·s) · A(audio)` — FBM (3–5 octaves) along the
   rim angle θ; amplitude split per band (see §3 wiring).
3. **Interior flow:** back-advect the shading coordinate along Bridson curl noise:
   `q = p − v(p, t)·τ`, where `v = (∂ψ/∂y, −∂ψ/∂x)`, `ψ = ramp(−d/d₀) · fbm(p·f, t·s)`
   (finite-difference curl, ε = 10⁻³; quintic ramp from the paper; d₀ = noise length scale).
   Shade the interior with `fbm(q)` → flowing internal currents that hug the rim.
4. **Monochrome shading:** interior value → **quantized grey bands** using ONLY brief inks:
   `#0A0A0A` base fill, currents in `#525252` at 8–14% mix, rim meniscus line 1.5px
   `#0A0A0A` at full strength, faint outer "wet edge" `#EDEDED` ring on the white canvas.
   Anti-alias by smoothstep on `d` over 1.25 device pixels. Background pure `#FFFFFF` —
   the canvas element is transparent; the app canvas shows through.
5. **No bloom, no shadow, no color.** Depth comes from band contrast and motion parallax
   (two curl layers at different scales moving at different speeds).

---

## 2. Emotion → physics parameter map (THE TABLE)

Affect contract (see `russell-1980-circumplex-model-of-affect/`):
`affect = { valence v ∈ [−1,1], arousal a ∈ [0,1], burst ∈ {none, laugh(intensity)} }`,
smoothed with a 600ms critically-damped ease before hitting uniforms. States below are
named regions of (v, a) — the shader interpolates continuously between them; it never
switches discretely.

| State (v, a) | flowSpeed (curl advection, R/s) | noiseFreq fᵣ (rim) / f (interior) | octaves | rimAmp (×R) | surfaceTension k (×R) | pulse pattern | envelope attack / decay | radius bias |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Idle / calm pool** (0, 0.1) | 0.04 | 1.2 / 1.6 | 3 | 0.015 | 0.30 | breathe: sine, period 2400ms (= `--dur-breathe`), depth 1.5% | 0.25 / 0.97 (viscous) | 1.00 |
| **Listening** (0, 0.35) | 0.12 | 1.4 / 1.8 | 3 | 0.03 × micEnv | 0.28 | mic-envelope ripples travel inward | 0.5 / 0.93 (house waveform constants) | 1.02 |
| **Thinking** (0.1, 0.45) | 0.18, radial-inward drift bias +0.05 | 1.0 / 2.2 | 4 | 0.02 | 0.26 | slow inward spiral, no pulses | 0.3 / 0.96 | 0.98 |
| **Speaking · neutral** (0.1, 0.5) | 0.25 | 1.5 / 2.0 | 4 | 0.05 × ttsEnv | 0.25 | word-rate pulses from Cartesia word timestamps | 0.5 / 0.93 | 1.02 |
| **Happy** (0.7, 0.6) | 0.32 | 1.0 / 1.6 (rounder swells) | 3 | 0.06 × ttsEnv | 0.34 (cohesive, buoyant) | vertical bob 0.3Hz depth 2%, rounded crests | 0.5 / 0.94 | 1.06 |
| **Laughing** (0.8, 0.85 + burst) | 0.38 | 1.3 / 1.8 | 4 | 0.08 | 0.20 → droplets detach & re-merge (2–4 satellites) | concentric ring pulses at syllable rate 4–6Hz, depth 8%, peaks +10% radius | 0.7 / 0.90 | 1.04 |
| **Agitated / alert** (−0.6, 0.9) | 0.50 | 2.8 / 3.2 (small fast vortices) | 5 | 0.07, sharp (higher harmonics) | 0.06 (tension breaks; jagged necking) | irregular micro-jitter 8–12Hz, amplitude spikes on flux | 0.8 / 0.85 (twitchy) | 0.97 |
| **Sad / subdued** (−0.5, 0.15) | 0.06 | 0.9 / 1.4 | 3 | 0.012 | 0.32 | slow settle, rest offset −2% (pool "sits lower") | 0.2 / 0.98 | 0.96 |
| **Error / fail-closed** (0, 0.2) | 0.05 | 1.2 / 1.6 | 3 | 0.01 | 0.30 | one inward collapse (300ms, `--ease-in-out`) then still; rim line weight 2px | — | 0.95 |

Continuous laws behind the table (arousal drives energy, valence drives shape — the
circumplex axes): `flowSpeed = 0.04 + 0.46·a` · `noiseFreq = 1.2 + 1.8·a` ·
`k = 0.30 + 0.06·max(v,0) − 0.24·a·max(−v,0)` · `radiusBias = 1 + 0.06·v·(0.5+0.5a)`.
The table rows are the canonical checkpoints these formulas must reproduce (test fixture).

Barge-in gesture: a single inward "swallow" deformation (rim pulled toward the interruption
onset, 200ms, `--ease-out`) → Listening. Interruption deforms the body; it never resets it.

---

## 3. Audio-analysis wiring spec

**Playback path (Naomi speaking).** Engine relays Cartesia PCM (`pcm_f32le`, 24000 Hz)
over the existing engine↔UI WebSocket → UI AudioWorklet ring buffer →
`AudioContext({ sampleRate: 24000 })` → `GainNode` (barge-in ramp) → destination, with an
`AnalyserNode` tap (`fftSize: 1024`, `smoothingTimeConstant: 0` — we do our own physics
smoothing). Per rAF frame compute:
- `ttsEnv` — RMS of time-domain buffer, then house attack/decay (0.5 / 0.93);
- band energies: low 0–300Hz → swell weight, mid 300–2k → rim ripple amplitude,
  high 2k–8k → interior fine-texture gain;
- `flux` — half-wave-rectified spectral difference vs previous frame → syllable pulses;
- word boundaries from Cartesia `add_timestamps` (via engine WS) → precise pulse train.

**Mic path (user speaking).** No second mic capture in the UI: reuse the engine's existing
per-stream levels (the design-brief waveform is already "driven by real levels"), streamed
at ~30Hz over WS as `micEnv` + VAD state. Keeps single-owner audio devices (capture stays
in `engine/audio/`).

**Affect path.** The LLM self-tags: the router prompt requires the response stream to open
with one line `<<affect v=+0.6 a=0.7 burst=laugh?>>` (stripped before display/TTS). The
engine parses → (v,a,burst) triple → (a) UI WS for shader uniforms, (b) quantized to
Cartesia `generation_config.emotion` ∈ {neutral, calm, angry, content, sad} + `speed`
(0.9 + 0.25·a), (c) laugh burst → inline `[laughter]` tag pass-through in transcript.
Fallback when the tag is missing/malformed: prosody heuristic — arousal from ttsEnv mean +
speaking rate (word-timestamp density), valence 0. Fail-open to neutral, never crash;
malformed tag text must NEVER reach TTS or the transcript display (treat as untrusted —
prompt-injection discipline at the model boundary, §5.6).

AnalyserNode API per MDN (Web Audio API, developer.mozilla.org — `AnalyserNode.fftSize`,
`getByteFrequencyData`, `getFloatTimeDomainData`).

---

## 4. Canvas & layout spec (Omni design system)

- **Placement:** Naomi view = full content area, `--canvas` white, nothing else on screen
  except: label `NAOMI` (JetBrains Mono 11px, `--label-ls` 0.08em, uppercase, `--grey-400`)
  top-left at `--space-12`; live caption line (Inter 400 15px `--grey-600`, current word
  `--ink`) centered `--space-8` below the pool; barge-in hint (mono 12px `--grey-400`).
- **Pool geometry:** centered, diameter `clamp(280px, 44vmin, 520px)`; vertical optical
  center at 46% viewport height.
- **Canvas element:** `width/height = cssSize × min(devicePixelRatio, 2) × renderScale`
  (renderScale from the performance governor, §5); CSS size set in px; resize via
  ResizeObserver debounced 100ms.
- **State is weight/scale/motion/depth:** state changes ride the motion table — view
  transitions 300ms `--ease-out`; entering Naomi uses the logo-aperture language ONLY at
  launch per brief §6.
- **The pool replaces the breathing ring while Naomi is foreground** — same 2400ms sine
  heartbeat, so tray ring and pool read as one organism. No new colors, no new shadows,
  no gradients beyond the permitted wash (not used inside the pool).

---

## 5. Performance budget + measurement plan

**Budget (60fps ⇒ 16.7ms):** GPU frame ≤ 6ms on Intel Iris Xe class; ≤ 2ms on discrete;
JS per frame ≤ 2ms (uniform packing + analyser reads only — zero allocations in the rAF
loop; pre-allocated typed arrays); main-thread long tasks 0 during speech.

**Governor:** rolling 120-frame p95 of rAF delta. If p95 > 17ms for 2s: renderScale
1.0 → 0.75 → 0.5, then octaves 5→3, then 30fps cap with time-dilation (motion stays
smooth, cadence halves). Recover upward hysteretically (30s stable). Log tier changes to
the dev console only (zero telemetry — local-only invariant).

**Measurement plan (CI + bench):**
- `EXT_disjoint_timer_query_webgl2` GPU timings where the driver exposes it; else rAF
  delta histograms; record p50/p95/p99 into the evidence suite.
- Playwright E2E: drive every state via a test hook (`window.__naomi.setAffect(v,a,burst)`
  exposed in dev builds only), assert canvas is painting (pixel sampling), assert
  reduced-motion freeze, capture per-state screenshots for the evidence folder.
- Golden-frame determinism test: fixed (t, audio, affect) uniforms ⇒ identical pixels
  across runs (readPixels hash) — the shader is a pure function; this is enforced.
- Bench page rendering the pool at 3 sizes × 3 renderScales, reporting FPS table (feeds
  `evidence/`).

## 6. Reduced-motion spec

`prefers-reduced-motion: reduce` (must be honored manually — canvas ignores the global CSS
`animation: none`): **Naomi is a still pool.** Render exactly one frame per state change:
frozen time uniform, envelope forced to its state's resting value, no rAF loop (redraw only
on state/affect change or resize, via a 300ms single-step parameter ease... no — *no
tweening*: draw the end state immediately, per brief "freeze all loops, keep end states").
Speaking is indicated by the caption line and by discrete weight changes: rim line 1.5px →
2px while audio plays. All information conveyed by motion has a static equivalent (WCAG 2.2).

---

## 7. Track B — the turn loop & latency budget

```
mic ──► engine/audio (WASAPI mic stream)
     ──► Silero VAD (engine/stt/vad_gating_state_machine.py)   [end-point ~200ms]
     ──► Parakeet streaming partials (local)                    [already streaming]
     ──► on end-of-speech: router → Groq (engine/router/provider_client_groq.py)
         with M3 hybrid retrieval context                       [TTFT ≤ 300ms]
     ──► token stream → affect tag parse → clause chunker
     ──► Cartesia WS (context_id, continue:true per clause, pcm_f32le@24k)
     ──► engine relays PCM + word timestamps → UI AudioWorklet  [TTFA 40–90ms]
     ──► GainNode → speakers  +  AnalyserNode → pool uniforms
```

**Latency budget (from user end-of-speech to first audible audio):**

| Stage | Component | Budget p50 | Budget p95 | Source |
| --- | --- | --- | --- | --- |
| End-of-speech detection | Silero VAD min-silence (Naomi profile) | 200ms | 280ms | voice-agent-latency research; local knob |
| Final transcript assembly | Parakeet partials already emitted; finalize | 30ms | 80ms | local, measured via transcription_latency_tracker |
| Retrieval | M3 hybrid (sqlite-vec, local) | 15ms | 40ms | local |
| LLM first sentence | Groq TTFT ≤300ms + ~12 tokens @ ≥300 tok/s ≈ 40ms | 280ms | 420ms | GroqDocs; Artificial Analysis |
| TTS first audio | Cartesia sonic-3.5 WS TTFA + RTT | 70ms | 130ms | Cartesia docs/benchmarks |
| Playout | WS relay + worklet ring buffer (2 quanta) | 25ms | 50ms | local |
| **Total** | | **≈ 620ms** | **≈ 1000ms** | **headline: p50 ≤ 650ms, p95 ≤ 1s** |

**Barge-in (user talks over Naomi):** VAD onset on mic (2 consecutive speech frames,
~60ms debounce — loopback/mic separation makes self-triggering structurally impossible) →
gain ramp to 0 in 20ms + flush ring buffer → Cartesia `{"context_id","cancel":true}` →
abort Groq stream → visual swallow gesture → listening. Perceived stop < 50ms. False-positive
discipline: prefer brief overlap over wrongly silencing Naomi.

**Security bindings (unchanged, binding):** keys engine-side only (`CARTESIA_API_KEY`,
`CARTESIA_VOICE_ID` via DPAPI store; never in the UI process, never logged); every Cartesia
call goes through the router ledger + audit log like any external call; kill-switch halts
Cartesia/Groq (Naomi degrades to text answers from local RAG — visual stays alive, it is
fully local); transcript content is untrusted input at every model boundary.

---

## 8. Implementation plan (build agent — execute in order)

1. **`apps/ui/src/naomi/` scaffolding** (names per §5.7, ≤300 lines/file):
   `naomi_pool_renderer_webgl2.ts` (context, tiers, governor),
   `naomi_pool_fragment_shader.glsl` (the §1 shader),
   `naomi_pool_canvas2d_fallback.ts` (Tier 3/4),
   `naomi_affect_parameter_mapper.ts` (§2 formulas + table checkpoints),
   `naomi_audio_feature_extractor.ts` (§3 analyser/worklet),
   `naomi_playback_audio_worklet.ts` (ring buffer + gain barge-in),
   `NaomiView.tsx` (layout §4, states, reduced-motion).
2. **Engine:** `engine/agents/` Naomi turn orchestrator + `engine/router/` Cartesia client
   (`provider_client_cartesia.py`, WS, pinned `sonic-3.5-2026-05-04`, cancel support,
   ledger + audit entries); VAD Naomi end-pointing profile; WS protocol messages
   (`naomi.audio_chunk`, `naomi.word_timestamps`, `naomi.affect`, `naomi.mic_level`,
   `naomi.state`).
3. **Tests first** (§5.5): golden-frame shader determinism; parameter-map table exactness
   (every row reproduced by the formulas, to the unit); affect-tag parser property/fuzz
   tests (malformed tags never leak to TTS/display); barge-in state machine tests
   (interrupt at every pipeline stage); latency assertions with fake clocks; Playwright
   E2E per §5 measurement plan.
4. **Evidence:** per-state screenshots, FPS/latency tables, and the flow diagram (black &
   white) into `evidence/naomi/`.

Open items deliberately left to the build phase: exact FBM octave weights (tune on-device
against the table's feel), droplet orbit choreography for laughter, and whether the caption
uses word-level highlight (timestamps make it free).
