/**
 * Tier ladder decision logic (brief §1): WebGL2 → WebGL1 → Canvas2D →
 * static, with SwiftShader/software GL forced down to Canvas2D and
 * nothing-available failing closed to Tier 4. Every branch, exactly.
 */
import { describe, expect, it } from "vitest";
import {
  chooseRenderTier,
  isSoftwareRenderer,
  type RenderCapabilities,
} from "./naomi-render-tier-ladder";

const caps = (overrides: Partial<RenderCapabilities>): RenderCapabilities => ({
  webgl2Available: false,
  webgl1Available: false,
  canvas2dAvailable: false,
  rendererString: null,
  ...overrides,
});

describe("chooseRenderTier", () => {
  it("Tier 1 when WebGL2 exists on real hardware", () => {
    expect(
      chooseRenderTier(caps({ webgl2Available: true, webgl1Available: true, canvas2dAvailable: true, rendererString: "NVIDIA GeForce RTX 4070" })),
    ).toBe(1);
  });

  it("Tier 1 when the renderer string is masked (trust the context)", () => {
    expect(chooseRenderTier(caps({ webgl2Available: true, rendererString: null }))).toBe(1);
  });

  it("Tier 2 when only WebGL1 exists", () => {
    expect(
      chooseRenderTier(caps({ webgl1Available: true, canvas2dAvailable: true, rendererString: "Intel(R) UHD Graphics" })),
    ).toBe(2);
  });

  it("Tier 3 when no GL at all but Canvas2D works", () => {
    expect(chooseRenderTier(caps({ canvas2dAvailable: true }))).toBe(3);
  });

  it("Tier 4 (static) when NOTHING probed — deny by default", () => {
    expect(chooseRenderTier(caps({}))).toBe(4);
  });

  it.each([
    "Google SwiftShader",
    "SwiftShader Device (Subzero)",
    "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)))",
    "llvmpipe (LLVM 15.0.7, 256 bits)",
    "Microsoft Basic Render Driver",
  ])("software GL %j drops PAST both GL tiers to Canvas2D", (renderer) => {
    expect(
      chooseRenderTier(
        caps({ webgl2Available: true, webgl1Available: true, canvas2dAvailable: true, rendererString: renderer }),
      ),
    ).toBe(3);
  });

  it("software GL with no Canvas2D fails closed to Tier 4", () => {
    expect(
      chooseRenderTier(caps({ webgl2Available: true, rendererString: "SwiftShader" })),
    ).toBe(4);
  });
});

describe("isSoftwareRenderer", () => {
  it("is case-insensitive", () => {
    expect(isSoftwareRenderer("SWIFTSHADER")).toBe(true);
    expect(isSoftwareRenderer("swiftshader")).toBe(true);
  });
  it("null (masked) is NOT software — the context is trusted", () => {
    expect(isSoftwareRenderer(null)).toBe(false);
  });
  it("real GPUs are not flagged", () => {
    expect(isSoftwareRenderer("ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11)")).toBe(false);
    expect(isSoftwareRenderer("Apple M3")).toBe(false);
    expect(isSoftwareRenderer("Intel(R) Iris(R) Xe Graphics")).toBe(false);
  });
});
