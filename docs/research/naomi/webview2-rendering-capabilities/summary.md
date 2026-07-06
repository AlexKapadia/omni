# WebView2 rendering reality-check — WebGL2 vs WebGPU under Tauri 2 on Windows

**Primary sources:**
- Microsoft Edge Team. "WebView2 browser flags." Microsoft Learn, updated 2026-06-24.
  https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/webview-features-flags
- Tauri. "Webview Versions." Tauri v2 reference. https://v2.tauri.app/reference/webview-versions/
- MicrosoftEdge/WebView2Feedback issue #1285 "WebGPU support in Webview2?" (opened 2021-05-15)
  https://github.com/MicrosoftEdge/WebView2Feedback/issues/1285 and tauri-apps/tauri
  issue #6381 "WebGPU support?" https://github.com/tauri-apps/tauri/issues/6381
**Surveyed:** 2026-07-06.

## Findings

1. **WebView2 is evergreen Chromium.** Tauri 2 on Windows renders through Microsoft Edge
   WebView2, which "is based on Microsoft Edge and therefore Chromium" and updates via
   the Evergreen distribution (Tauri webview-versions reference; Microsoft WebView2
   distribution docs). Chromium's stable feature set therefore applies.
2. **WebGL2 is a safe bet.** WebGL2 has been stable in Chromium since Chrome 56 (2017)
   and ships in Edge/WebView2 unconditionally, GPU-accelerated through the Chromium GPU
   process (falls back to SwiftShader software rasterization only on blocklisted drivers —
   detectable via the `WEBGL_debug_renderer_info` unmasked renderer string).
3. **WebGPU in WebView2 is NOT a dependable target.** Community reports are mixed on
   whether `navigator.gpu` is exposed/functional in WebView2 across runtime versions and
   devices (WebView2Feedback #1285, #4138; tauri#6381 documents no supported way to
   enable it from Tauri config). Where it needs flags, Microsoft's own flags doc is
   explicit and binding for a production app:
   > "Apps in production shouldn't use WebView2 browser flags, because these flags might
   > be removed or altered at any time, and aren't necessarily supported long-term."
   (Flags mechanisms, for dev only: `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` env var,
   registry, or `CoreWebView2EnvironmentOptions.AdditionalBrowserArguments`.)
4. **Consequence:** any Naomi design must run fully on **WebGL2 without optional
   float-render extensions in its primary tier**; WebGPU may only ever be an
   opportunistic, runtime-probed enhancement (`if (navigator.gpu && await
   navigator.gpu.requestAdapter())`), never a requirement — and v1 should not ship a
   WebGPU path at all (dead code risk for an unreachable tier).

## Fallback ladder mandated by this evidence

1. **Tier 1 (primary): WebGL2, single-pass fragment shader, no FBOs, no float
   attachments** — works on every non-blocklisted WebView2 install.
2. **Tier 2: WebGL1** — same shader ported to GLSL ES 1.00 (no `#version 300 es`); only
   needed for blocklist edge cases where WebGL2 context creation fails but WebGL1 works.
3. **Tier 3: Canvas2D** — analytic blob (harmonic rim displacement, radial-gradient
   greys), ~1-2ms/frame; covers SwiftShader-slow machines.
4. **Tier 4: static render** — one frame of Tier 3 (also the prefers-reduced-motion and
   kill-switch-irrelevant offline visual; Naomi visual is fully local either way).
