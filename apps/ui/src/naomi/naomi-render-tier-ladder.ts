/**
 * Render-tier fallback ladder (brief §1): probe at boot, never assume.
 *
 *   Tier 1  WebGL2 single-pass shader (primary)
 *   Tier 2  WebGL1, same shader as GLSL ES 1.00
 *   Tier 3  Canvas2D analytic pool (also forced when the GL is SwiftShader —
 *           software rasterisation would silently burn CPU for a "GPU" path)
 *   Tier 4  static frame of Tier 3 (zero-GPU / no-canvas path)
 *
 * The DECISION is a pure function of the probed capabilities so it is
 * exactly testable; the probe itself is the only DOM-touching part.
 */

export type RenderTier = 1 | 2 | 3 | 4;

/** What the boot probe learned about this machine. */
export interface RenderCapabilities {
  readonly webgl2Available: boolean;
  readonly webgl1Available: boolean;
  readonly canvas2dAvailable: boolean;
  /** UNMASKED_RENDERER_WEBGL string when exposed, else null. */
  readonly rendererString: string | null;
}

// Software rasterisers that must never carry the shader path (brief §1:
// "Also auto-selected when WEBGL_debug_renderer_info reports SwiftShader").
const SOFTWARE_RENDERER_MARKERS = ["swiftshader", "llvmpipe", "software", "microsoft basic render"];

/** Is the reported GL renderer actually software? Case-insensitive. */
export function isSoftwareRenderer(rendererString: string | null): boolean {
  if (rendererString === null) return false; // masked info: trust the context
  const lowered = rendererString.toLowerCase();
  return SOFTWARE_RENDERER_MARKERS.some((marker) => lowered.includes(marker));
}

/** The pure tier decision. Deny-by-default: nothing probed → Tier 4. */
export function chooseRenderTier(caps: RenderCapabilities): RenderTier {
  const software = isSoftwareRenderer(caps.rendererString);
  if (caps.webgl2Available && !software) return 1;
  if (caps.webgl1Available && !software) return 2;
  if (caps.canvas2dAvailable) return 3;
  return 4;
}

function unmaskedRenderer(gl: WebGLRenderingContext | WebGL2RenderingContext): string | null {
  try {
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    if (info === null) return null;
    const value: unknown = gl.getParameter(info.UNMASKED_RENDERER_WEBGL);
    return typeof value === "string" ? value : null;
  } catch {
    return null; // a hostile/broken driver must not crash the probe
  }
}

/**
 * Probe real capabilities using throwaway canvases. Contexts are created
 * once here and immediately released; the renderer creates its own on the
 * live canvas after the tier is chosen.
 */
export function probeRenderCapabilities(
  createCanvas: () => HTMLCanvasElement = () => document.createElement("canvas"),
): RenderCapabilities {
  let webgl2Available = false;
  let webgl1Available = false;
  let canvas2dAvailable = false;
  let rendererString: string | null = null;
  try {
    const gl2 = createCanvas().getContext("webgl2");
    if (gl2 !== null) {
      webgl2Available = true;
      rendererString = unmaskedRenderer(gl2);
      gl2.getExtension("WEBGL_lose_context")?.loseContext();
    }
  } catch {
    /* fail closed to the next tier */
  }
  try {
    const gl1 = createCanvas().getContext("webgl");
    if (gl1 !== null) {
      webgl1Available = true;
      if (rendererString === null) rendererString = unmaskedRenderer(gl1);
      gl1.getExtension("WEBGL_lose_context")?.loseContext();
    }
  } catch {
    /* fail closed to the next tier */
  }
  try {
    canvas2dAvailable = createCanvas().getContext("2d") !== null;
  } catch {
    /* fail closed to Tier 4 */
  }
  return { webgl2Available, webgl1Available, canvas2dAvailable, rendererString };
}
