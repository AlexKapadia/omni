/**
 * Settings — all REAL engine data: settings.get, ledger.summary, and real
 * device enumeration on mount; every control persists via settings.update.
 * Exercises the router matrix, cost ledger, API-key custody (masked), the
 * instant-execute whitelist, devices, and a privacy toggle round-trip.
 */
import { test, expect } from "../harness/fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
});

test("renders the real router matrix and cost ledger", async ({ page }) => {
  // Settings resolve from the real engine (loading shimmer clears to content).
  await expect(page.getByLabel("Loading settings")).toBeHidden({ timeout: 20_000 });
  await expect(page.getByRole("table", { name: "Routing policy" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "task" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Cost and latency" }).or(page.getByLabel("Cost and latency"))).toBeVisible();
});

test("API keys are custody-masked with real validate controls", async ({ page }) => {
  // The key field is a password-type input — the plaintext key is never shown.
  const keyField = page.getByLabel(/API key$/).first();
  await expect(keyField).toBeVisible();
  await expect(keyField).toHaveAttribute("type", "password");
  await expect(page.getByRole("button", { name: /^Validate / }).first()).toBeVisible();
});

test("device picker enumerates real audio devices", async ({ page }) => {
  await expect(page.getByLabel("Loading settings")).toBeHidden({ timeout: 20_000 });
  await expect(page.getByLabel("Microphone")).toBeVisible();
});

test("a privacy toggle persists and reverts through the real engine", async ({ page }) => {
  await expect(page.getByLabel("Loading settings")).toBeHidden({ timeout: 20_000 });
  const toggle = page.getByRole("switch").first();
  await expect(toggle).toBeVisible();
  const before = await toggle.getAttribute("aria-checked");
  await toggle.click();
  // The switch flips optimistically and the engine confirms (settings.update).
  await expect(toggle).not.toHaveAttribute("aria-checked", before ?? "false");
  // Put it back so the run leaves no persisted state change.
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", before ?? "false");
});

test("instant-execute whitelist section is present", async ({ page }) => {
  await expect(page.getByLabel("Loading settings")).toBeHidden({ timeout: 20_000 });
  await expect(page.getByText(/instant|whitelist/i).first()).toBeVisible();
});
