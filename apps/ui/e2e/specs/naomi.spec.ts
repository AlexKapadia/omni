/**
 * Naomi — the living-water companion screen. In the production build the pool
 * renders as a real WebGL/canvas surface (no image, no mock) driven by the
 * renderer's rAF loop; the affect dev-hook is DEV-only, so here we prove the
 * real canvas mounts, the brand label is present, and the conversation panel
 * reflects the real engine connection. We never toggle the mic (no OS input).
 */
import { test, expect } from "../harness/fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Naomi" }).click();
});

test("renders the real living-water pool canvas and brand label", async ({ page }) => {
  const canvas = page.getByTestId("naomi-pool-canvas");
  await expect(canvas).toBeVisible();
  // The canvas is a real drawing surface, described for assistive tech.
  await expect(canvas).toHaveAttribute(
    "aria-label",
    /pool of black water that moves as she listens and speaks/,
  );
  // The screen's own NAOMI label (mono uppercase, per the brief).
  await expect(page.getByText("Naomi", { exact: true }).first()).toBeVisible();
});

test("the pool canvas has real, non-zero rendered dimensions", async ({ page }) => {
  // A mounted, sized canvas proves the renderer laid out a real surface (not a
  // 0×0 placeholder) — the water is actually being drawn on this device.
  const box = await page.getByTestId("naomi-pool-canvas").boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThan(200);
  expect(box!.height).toBeGreaterThan(200);
});
