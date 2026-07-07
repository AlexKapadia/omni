/**
 * Onboarding — the first-run wizard (design §09), driven end-to-end as its own
 * flow against the REAL engine. The app only shows the wizard when setup is
 * incomplete, so we flip the real onboarding_complete setting off (a valid
 * settings.update key), walk all four steps with real state transitions and a
 * REAL vault configuration, then restore the setting so the rest of the suite
 * boots straight to the Library. Nothing here is mocked; the Finish gate stays
 * bound to the engine's own truth (keys must really validate) — we assert that
 * honest gate rather than faking it open.
 */
import { test, expect } from "../harness/fixtures";
import { setOnboardingComplete } from "../harness/engine-command";

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  await setOnboardingComplete(false); // real engine: force the first-run wizard
});

test.afterAll(async () => {
  await setOnboardingComplete(true); // restore so other specs boot to Library
});

test("walks all four real steps: welcome → vault → keys → models", async ({ page }) => {
  await page.goto("/");

  // Step 1 — Welcome. The hero lockup and the single real action.
  await expect(page.getByRole("heading", { name: "Omni", level: 1 })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Begin" }).click();

  // Step 2 — Vault. Configure a REAL folder (the shim returns the fixture vault
  // path through the same OS-picker seam the app uses in production).
  await expect(page.getByRole("heading", { name: "Choose your vault" })).toBeVisible();
  const cont = page.getByRole("button", { name: "Continue" });
  if (!(await cont.isEnabled())) {
    await page.getByRole("button", { name: "Browse" }).click();
    await page.getByRole("button", { name: /Use this folder|Folder set/ }).click();
  }
  await expect(cont).toBeEnabled({ timeout: 15_000 });
  await cont.click();

  // Step 3 — Keys. Real per-provider masked fields (deny-by-default until valid).
  await expect(page.getByRole("heading", { name: "Add your keys" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Groq API key" })).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 4 — Models + the honest Finish gate. The seeded model files are
  // present, so the real state is "models ready"; Finish stays bound to the
  // engine's own truth — it is DISABLED until the required keys really validate
  // (we assert that honest gate rather than faking it open).
  await expect(page.getByRole("heading", { name: "Get the models" })).toBeVisible();
  await expect(page.getByText("✓ models ready")).toBeVisible();
  await expect(page.getByRole("button", { name: "Finish" })).toBeDisabled();
  await expect(page.getByText(/To finish, validate your .* keys/)).toBeVisible();

  // Back navigation is a real transition too (returns to the keys step).
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("heading", { name: "Add your keys" })).toBeVisible();
});

test("restoring setup boots straight into the Library shell", async ({ page }) => {
  // Prove the wizard is genuinely gated on the engine's setup.status: with the
  // setting restored, a fresh boot lands on the main shell, not the wizard.
  await setOnboardingComplete(true);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Omni", level: 1 })).toBeHidden();
});
