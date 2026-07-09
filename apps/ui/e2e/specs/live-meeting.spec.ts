/**
 * Live meeting — the flagship capture screen. The full live layout (notepad +
 * flowing transcript + answers) only exists during an ACTIVE capture, which
 * needs real WASAPI/mic audio and loaded STT models. In this headless harness
 * we deliberately do NOT start capture: we must never record the user's real
 * audio, and the seeded model files are placeholders that cannot transcribe.
 * So this suite proves every REAL pre-capture state instead — the honest,
 * fully-wired states a user actually sees before a meeting starts.
 *
 * (The real flowing-transcript rendering is covered by the seeded meeting's
 * transcript in library.spec — real segments, real streams, over meeting.get.)
 */
import { test, expect } from "../harness/fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Record" }).click();
  await expect(page.getByRole("heading", { name: "Record a meeting" })).toBeVisible();
});

test("shows the idle pre-capture state with the real privacy promise", async ({ page }) => {
  // The bot-free / local-only promise is a first-class UI element (design §10.7).
  await expect(
    page.getByText(/No bot joins the call and nothing leaves this machine/),
  ).toBeVisible();
});

test("Start capture is wired and enabled while the engine is connected", async ({ page }) => {
  // With the real engine up, the primary action is live (not the disabled
  // engine-offline state). We assert it is enabled but never click it — that
  // would capture the user's real system audio, which this harness must not do.
  const start = page.getByRole("button", { name: "Start capture" });
  await expect(start).toBeVisible();
  await expect(start).toBeEnabled({ timeout: 20_000 });
  // The honest offline caption must be ABSENT while the engine is genuinely up.
  await expect(page.getByText(/The engine is offline — capture needs the engine/)).toBeHidden();
});
