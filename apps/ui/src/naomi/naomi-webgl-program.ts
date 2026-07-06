/**
 * WebGL plumbing for the pool shader: context creation, shader compile/link
 * (fail closed — a compile error returns null so the tier ladder drops,
 * never a black panel), the full-screen triangle, and uniform upload.
 *
 * Used by naomi-pool-renderer.ts for Tier 1 (WebGL2/ES300) and Tier 2
 * (WebGL1/ES100). Per-frame work is uniforms-only (brief §5 budget): the
 * geometry and program are immutable after setup.
 */

import {
  FULLSCREEN_TRIANGLE_VERTICES,
  POOL_FRAGMENT_SHADER_ES100,
  POOL_FRAGMENT_SHADER_ES300,
  POOL_UNIFORM_NAMES,
  POOL_VERTEX_SHADER_ES100,
  POOL_VERTEX_SHADER_ES300,
  type PoolUniformName,
} from "./naomi-pool-fragment-shader";
import type { NaomiUniformValues } from "./naomi-pool-uniforms";

type Gl = WebGLRenderingContext | WebGL2RenderingContext;

export interface PoolGlProgram {
  readonly gl: Gl;
  readonly locations: Record<PoolUniformName, WebGLUniformLocation | null>;
}

function compile(gl: Gl, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (shader === null) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    // Dev-console only (zero telemetry — local-only invariant).
    console.error("naomi pool shader compile failed:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

/**
 * Create the GL context + program on `canvas` for the given tier.
 * Returns null on ANY failure so the caller falls to the next tier.
 */
export function createPoolGlProgram(
  canvas: HTMLCanvasElement,
  tier: 1 | 2,
): PoolGlProgram | null {
  // alpha+premultiplied: the pool composites over the app's white canvas.
  const attributes: WebGLContextAttributes = {
    alpha: true,
    premultipliedAlpha: true,
    antialias: false, // AA is done analytically in the shader (smoothstep on d)
    depth: false,
    stencil: false,
    powerPreference: "low-power", // a pool should sip, not gulp
  };
  const gl =
    tier === 1
      ? (canvas.getContext("webgl2", attributes) as WebGL2RenderingContext | null)
      : (canvas.getContext("webgl", attributes) as WebGLRenderingContext | null);
  if (gl === null) return null;

  const vertexSource = tier === 1 ? POOL_VERTEX_SHADER_ES300 : POOL_VERTEX_SHADER_ES100;
  const fragmentSource = tier === 1 ? POOL_FRAGMENT_SHADER_ES300 : POOL_FRAGMENT_SHADER_ES100;
  const vertex = compile(gl, gl.VERTEX_SHADER, vertexSource);
  const fragment = compile(gl, gl.FRAGMENT_SHADER, fragmentSource);
  if (vertex === null || fragment === null) return null;

  const program = gl.createProgram();
  if (program === null) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.bindAttribLocation(program, 0, "a_position");
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error("naomi pool program link failed:", gl.getProgramInfoLog(program));
    return null;
  }
  gl.useProgram(program);

  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, FULLSCREEN_TRIANGLE_VERTICES, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

  gl.disable(gl.BLEND); // shader outputs final premultiplied color directly
  gl.clearColor(0, 0, 0, 0);

  const locations = {} as Record<PoolUniformName, WebGLUniformLocation | null>;
  for (const name of POOL_UNIFORM_NAMES) {
    locations[name] = gl.getUniformLocation(program, name);
  }
  return { gl, locations };
}

/** Upload one frame's uniforms and draw. Zero allocations. */
export function drawPoolGlFrame(
  program: PoolGlProgram,
  values: NaomiUniformValues,
  widthPx: number,
  heightPx: number,
  poolRadiusPx: number,
): void {
  const { gl, locations } = program;
  gl.viewport(0, 0, widthPx, heightPx);
  gl.uniform2f(locations.u_resolution, widthPx, heightPx);
  gl.uniform1f(locations.u_poolRadiusPx, poolRadiusPx);
  gl.uniform1f(locations.u_time, values.time);
  gl.uniform4fv(locations.u_audio, values.audio);
  gl.uniform1f(locations.u_audioPulse, values.audioPulse);
  gl.uniform4fv(locations.u_flow, values.flow);
  gl.uniform4fv(locations.u_shape, values.shape);
  gl.uniform4fv(locations.u_pulseA, values.pulseA);
  gl.uniform4fv(locations.u_pulseB, values.pulseB);
  gl.uniform2fv(locations.u_droplet, values.droplet);
  gl.uniform1f(locations.u_errorWeight, values.errorWeight);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
}
