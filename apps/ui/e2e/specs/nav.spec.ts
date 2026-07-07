/**
 * Navigation + shell smoke: the REAL app boots past the setup gate into the
 * main shell (proving setup.status came back complete from the real engine),
 * every nav-rail row switches the active screen, and the status footer shows
 * the live engine state. This is also the pipeline smoke for the whole suite.
 */
import { test, expect } from "../harness/fixtures";

test.describe("shell + navigation", () => {
  test("boots into the main shell and navigates every section", async ({ page }) => {
    await page.goto("/");

    // Past the boot gate: the primary nav rail is the main shell (not the wizard).
    const nav = page.getByRole("navigation", { name: "Primary" });
    await expect(nav).toBeVisible();
    await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();

    // Every rail row fires its real state transition (aria-current tracks it).
    for (const [label, heading] of [
      ["Live meeting", "Live meeting"],
      ["Ask Omni", "Ask across everything you know"],
      ["Settings", "Settings"],
      ["Library", "Library"],
    ] as const) {
      await nav.getByRole("button", { name: label }).click();
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expect(nav.getByRole("button", { name: label })).toHaveAttribute(
        "aria-current",
        "page",
      );
    }

    // Naomi renders its live canvas (real WebGL/canvas2d, not an image).
    await nav.getByRole("button", { name: "Naomi" }).click();
    await expect(page.getByTestId("naomi-pool-canvas")).toBeVisible();
  });

  test("status footer reflects the live engine connection", async ({ page }) => {
    await page.goto("/");
    const footer = page.getByLabel("Engine status");
    await expect(footer).toBeVisible();
    // The engine is genuinely up, so a real heartbeat must flip the status dot
    // to "connected" (an open socket alone is not enough — protocol.ts gates it).
    await expect(footer.locator('[data-status="connected"]')).toBeVisible({ timeout: 20_000 });
    // A real ping/pong round-trip renders a numeric latency (never the "— ms" idle).
    await expect(page.getByLabel("Engine round-trip latency")).toContainText(/\d+\s*ms/);
  });
});
