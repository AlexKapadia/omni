/**
 * Onboarding — first-run wizard driven end-to-end against the REAL engine.
 * Required path: welcome → speaker (skippable) → vault → local models download.
 * Finish requires vault + on-device models; API keys and calendar are optional.
 */
import { test, expect } from "../harness/fixtures";
import { setOnboardingComplete } from "../harness/engine-command";

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  await setOnboardingComplete(false);
});

test.afterAll(async () => {
  await setOnboardingComplete(true);
});

test("finishes after vault and local models; keys and calendar are optional", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Omni Steroid", level: 1 })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Record your first meeting" }).click();

  await expect(page.getByRole("heading", { name: "Your voice in meetings" })).toBeVisible();
  await page.getByRole("button", { name: "Skip for now" }).click();

  await expect(page.getByRole("heading", { name: "Choose your vault" })).toBeVisible();
  const browse = page.getByRole("button", { name: "Browse" });
  if (await browse.isVisible()) {
    await browse.click();
    await page.getByRole("button", { name: /Use this folder|Folder set/ }).click();
  }
  await expect(page.getByText("✓ folder ready")).toBeVisible({ timeout: 15_000 });

  // Vault alone cannot finish — models are required.
  await expect(page.getByRole("button", { name: "Finish" })).toBeHidden();
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Set up on-device transcription" })).toBeVisible();
  // Auto-download starts on entry; wait for completion or retry if needed.
  const retry = page.getByRole("button", { name: "Retry download" });
  if (await retry.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await retry.click();
  }
  await expect(page.getByText("✓ Transcription ready")).toBeVisible({ timeout: 120_000 });

  const finish = page.getByRole("button", { name: "Finish" });
  await expect(finish).toBeEnabled();

  // Optional extras remain reachable and skippable.
  await page.getByRole("button", { name: "Set up API keys" }).click();
  await expect(page.getByRole("heading", { name: "Add your keys" })).toBeVisible();
  await page.getByRole("button", { name: "Skip for now" }).click();
  await expect(page.getByRole("heading", { name: "Connect Google Calendar" })).toBeVisible();
  await page.getByRole("button", { name: "Skip for now" }).click();

  await finish.click();
  await expect(page.getByRole("heading", { name: "Meetings", level: 1 })).toBeVisible({ timeout: 20_000 });
});

test("restoring setup boots straight into the Library shell", async ({ page }) => {
  await setOnboardingComplete(true);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Meetings", level: 1 })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Omni Steroid", level: 1 })).toBeHidden();
});
