# Best parts to take — WebView2 rendering reality-check

1. **Design to WebGL2-no-extensions as the primary tier.** The single decision that
   protects the whole feature: one full-screen fragment shader, vertex buffer of one
   triangle, zero framebuffer objects, zero float render targets.
2. **Never gate the product on browser flags** — Microsoft's flags doc forbids them in
   production; therefore no WebGPU dependency, no `AdditionalBrowserArguments` in the
   shipped Tauri config for rendering features.
3. **Probe, don't assume, at boot:** context creation try-order `webgl2` → `webgl` →
   `2d`; read `WEBGL_debug_renderer_info` to detect SwiftShader (software) and drop to
   Tier 3 immediately rather than rendering GL at 12fps.
4. **Keep the ladder honest:** every tier renders the same *design* (black pool, same
   states) at decreasing motion fidelity — never a spinner, never a blank div.
