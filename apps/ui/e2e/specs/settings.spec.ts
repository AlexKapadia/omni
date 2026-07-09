/**
 * Settings — all REAL engine data: settings.get, ledger.summary, and real
 * device enumeration on mount; every control persists via settings.update.
 *
 * The surface is now two-tier: Essentials (default) and Advanced. Power
 * controls — the router matrix, cost ledger, API keys, devices, and the
 * auto-run whitelist — live under Advanced, so these tests switch tiers before
 * exercising them, then verify the real engine data behind each.
 */
import { test, expect } from "../harness/fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  // The two-tier tablist renders immediately; Essentials is the default tier.
  await expect(page.getByRole("tab", { name: "Essentials" })).toHaveAttribute("aria-selected", "true");
});

/** Reveal the Advanced tier (router, usage, devices, automation, diagnostics). */
async function openAdvanced(page: import("@playwright/test").Page): Promise<void> {
  await page.getByRole("tab", { name: "Advanced" }).click();
  await expect(page.getByRole("tab", { name: "Advanced" })).toHaveAttribute("aria-selected", "true");
}

test("Essentials is the default tier and Advanced reveals power controls", async ({ page }) => {
  // Essentials groups are present without opening anything.
  await expect(page.getByRole("region", { name: "Your voice" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Transcription quality" })).toBeVisible();
  // Advanced-only groups are hidden until the user switches tiers.
  await expect(page.getByRole("region", { name: "API keys" })).toHaveCount(0);
  await openAdvanced(page);
  await expect(page.getByRole("region", { name: "Diagnostics" })).toBeVisible();
});

test("renders the real router matrix and cost ledger from engine data", async ({ page }) => {
  await openAdvanced(page);
  // The routing matrix is collapsed by default — expand the disclosure.
  await expect(page.getByRole("table", { name: "Routing policy" })).toBeHidden();
  await page.getByText("Provider routing matrix").click();
  const matrix = page.getByRole("table", { name: "Routing policy" });
  await expect(matrix).toBeVisible({ timeout: 20_000 });
  await expect(matrix.getByRole("columnheader", { name: "task" })).toBeVisible();
  await expect(matrix.getByRole("columnheader", { name: "route" })).toBeVisible();
  // The engine's real on-device rows are always present and never leave the box.
  await expect(matrix.getByRole("rowheader", { name: "transcription" })).toBeVisible();
  await expect(matrix.getByRole("rowheader", { name: "ask_synthesis" })).toBeVisible();
  // The real cost + latency ledger (populated by this run's own ask.query).
  await expect(page.getByRole("region", { name: "Cost and latency" })).toBeVisible();
});

test("API keys are custody-masked password fields with the on-device guarantee", async ({ page }) => {
  await openAdvanced(page);
  // The key field is a password-type input — the plaintext key is never shown.
  const keyField = page.getByRole("textbox", { name: "Groq API key" });
  await expect(keyField).toBeVisible();
  await expect(keyField).toHaveAttribute("type", "password");
  // The privacy guarantee is a first-class UI element, not fine print.
  await expect(
    page.getByText("Keys are encrypted on this device and never leave it."),
  ).toBeVisible();
});

test("device picker enumerates real audio devices", async ({ page }) => {
  await openAdvanced(page);
  await expect(page.getByLabel("Microphone")).toBeVisible();
});

test("a privacy toggle persists and reverts through the real engine", async ({ page }) => {
  // Disclosure reminder is benign (unlike pausing cloud AI) — safe to flip twice.
  // It lives under Essentials, so no tier switch is needed.
  const toggle = page.getByRole("switch", { name: "Disclosure reminder" });
  await expect(toggle).toBeVisible();
  const before = await toggle.getAttribute("aria-checked");
  await toggle.click();
  // The switch flips optimistically and the engine confirms (settings.update).
  await expect(toggle).not.toHaveAttribute("aria-checked", before ?? "false");
  // Put it back so the run leaves no persisted state change.
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", before ?? "false");
});

test("the auto-run whitelist is a real deny-by-default security surface", async ({ page }) => {
  await openAdvanced(page);
  // Every intent defaults OFF (deny by default, §5.6) with a real per-intent switch.
  const createEvent = page.getByRole("switch", { name: "Auto-run Create calendar events" });
  await expect(createEvent).toBeVisible();
  await expect(createEvent).toHaveAttribute("aria-checked", "false");
  // The draft-email intent is present and, like all of them, defaults OFF
  // (an approval card is required each time until explicitly whitelisted).
  await expect(page.getByText("Draft emails")).toBeVisible();
  const draftEmail = page.getByRole("switch", { name: "Auto-run Draft emails" });
  await expect(draftEmail).toHaveAttribute("aria-checked", "false");
});
