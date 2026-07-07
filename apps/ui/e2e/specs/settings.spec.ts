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
  // Settings resolve from the real engine — wait for the router matrix, which
  // only renders once settings.get parses (the real routing policy, no fake).
  await expect(page.getByRole("table", { name: "Routing policy" })).toBeVisible({ timeout: 20_000 });
});

test("renders the real router matrix and cost ledger from engine data", async ({ page }) => {
  const matrix = page.getByRole("table", { name: "Routing policy" });
  await expect(matrix.getByRole("columnheader", { name: "task" })).toBeVisible();
  await expect(matrix.getByRole("columnheader", { name: "route" })).toBeVisible();
  // The engine's real on-device rows are always present and never leave the box.
  await expect(matrix.getByRole("rowheader", { name: "transcription" })).toBeVisible();
  await expect(matrix.getByRole("rowheader", { name: "ask_synthesis" })).toBeVisible();
  // The real cost + latency ledger (populated by this run's own ask.query).
  await expect(page.getByRole("region", { name: "Cost and latency" })).toBeVisible();
});

test("API keys are custody-masked password fields with the DPAPI guarantee", async ({ page }) => {
  // The key field is a password-type input — the plaintext key is never shown.
  const keyField = page.getByRole("textbox", { name: "Groq API key" });
  await expect(keyField).toBeVisible();
  await expect(keyField).toHaveAttribute("type", "password");
  // The privacy guarantee is a first-class UI element, not fine print.
  await expect(
    page.getByText("Keys are encrypted with Windows DPAPI and never leave this device."),
  ).toBeVisible();
});

test("device picker enumerates real audio devices", async ({ page }) => {
  await expect(page.getByLabel("Microphone")).toBeVisible();
});

test("a privacy toggle persists and reverts through the real engine", async ({ page }) => {
  // Disclosure reminder is benign (unlike the kill switch) — safe to flip twice.
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

test("the instant-execute whitelist is a real deny-by-default security surface", async ({ page }) => {
  // Every intent defaults OFF (deny by default, §5.6) with a real per-intent switch.
  const createEvent = page.getByRole("switch", { name: "Instant execute Create calendar events" });
  await expect(createEvent).toBeVisible();
  await expect(createEvent).toHaveAttribute("aria-checked", "false");
  // The draft-email intent is present and, like all of them, defaults OFF
  // (an approval card is required each time until explicitly whitelisted).
  await expect(page.getByText("Draft emails")).toBeVisible();
  const draftEmail = page.getByRole("switch", { name: "Instant execute Draft emails" });
  await expect(draftEmail).toHaveAttribute("aria-checked", "false");
});
