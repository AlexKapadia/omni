/**
 * Real-product showcase media (§4.9.8): genuinely RECORDED (Playwright
 * recordVideo, never AI-generated) walk-through of the RUNNING app against the
 * REAL engine + real seeded data — never mock mode. Every captured state is
 * health-gated to a genuine success first (e.g. a real ask.answer must render
 * before we screenshot it) so nothing is passed off as more than it is.
 *
 * Outputs: per-screen PNGs at @2x (crisp, legibly framed) under media/
 * screenshots/, and the whole journey as one recorded video (converted to
 * mp4 + gif by the post-processing step). Honest caption note: the app runs in
 * a headless browser with a thin Tauri shim for OS-native seams only (folder
 * picker, tray) — all data flows through the real engine over the real socket.
 */
import { mkdirSync } from "node:fs";
import { test, expect } from "../harness/fixtures";
import { SCREENSHOTS_DIR } from "../harness/e2e-env";
import { setOnboardingComplete } from "../harness/engine-command";

mkdirSync(SCREENSHOTS_DIR, { recursive: true });

/** Screenshot the current viewport at the media dir (crisp @2x from config). */
async function shot(page: import("@playwright/test").Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SCREENSHOTS_DIR}/${name}.png` });
}

test("real product tour — library, meeting, ask, settings, naomi", async ({ page }) => {
  await page.goto("/");

  // 1) Meetings home — real seeded meetings (wait for a real row, not the race).
  await expect(page.getByRole("heading", { name: "Meetings", level: 1 })).toBeVisible();
  const firstMeeting = page.getByRole("button", { name: "Open Northwind Renewal" });
  await expect(firstMeeting).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(600); // let view-transition settle for a clean frame
  await shot(page, "01-library");

  // 2) Meeting detail — real enhanced notes + suggested actions + transcript.
  await firstMeeting.click();
  const pane = page.getByRole("complementary", { name: "Meeting detail" });
  await expect(pane.getByText(/24-month term/)).toBeVisible();
  await pane.getByText(/\d+ segments — click to expand/).click();
  await expect(pane.getByText(/twelve percent uplift/i)).toBeVisible();
  await page.waitForTimeout(400);
  await shot(page, "02-meeting-detail");
  await page.getByRole("button", { name: "Close meeting detail" }).click();

  // 3) Ask — a REAL answer with real citations (health-gated success).
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("heading", { name: "Ask about your meetings" })).toBeVisible();
  await page.getByRole("textbox", { name: "Ask" }).fill("What did we agree on the Northwind renewal?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible({ timeout: 40_000 });
  await expect(page.getByRole("button", { name: /\.md · L\d+/ }).first()).toBeVisible();
  await expect(page.getByLabel("Answer latency")).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "03-ask-answer");

  // 4) Settings — real router matrix + cost ledger + masked keys.
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("table", { name: "Routing policy" })).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(400);
  await shot(page, "04-settings-router");
  // Scroll the settings pane (its own overflow container) down to reveal the
  // lower half — privacy toggles, instant-execute, cost ledger + masked keys.
  await page.getByRole("heading", { name: "Settings", level: 1 }).evaluate((h) => {
    const scroller = h.closest(".overflow-y-auto");
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  });
  await page.waitForTimeout(500);
  await shot(page, "05-settings-ledger-keys");

  // 5) Naomi — the real living-water pool (WebGL surface, rAF loop running).
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Naomi" }).click();
  await expect(page.getByTestId("naomi-pool-canvas")).toBeVisible();
  await page.waitForTimeout(1200); // let the water settle into a striking frame
  await shot(page, "06-naomi-pool");
});

test("real onboarding walk-through — the four first-run steps", async ({ page }) => {
  // Show the genuine first-run wizard by flipping the real setting off, then
  // restore it so the app is left in its normal setup-complete state.
  await setOnboardingComplete(false);
  try {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Omni Steroid", level: 1 })).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(500);
    await shot(page, "07-onboarding-welcome");

    await page.getByRole("button", { name: "Begin" }).click();
    await expect(page.getByRole("heading", { name: "Choose your vault" })).toBeVisible();
    await page.waitForTimeout(300);
    await shot(page, "08-onboarding-vault");

    const cont = page.getByRole("button", { name: "Continue" });
    if (!(await cont.isEnabled())) {
      await page.getByRole("button", { name: "Browse" }).click();
      await page.getByRole("button", { name: /Use this folder|Folder set/ }).click();
    }
    await cont.click();
    await expect(page.getByRole("heading", { name: "Add your keys" })).toBeVisible();
    await page.waitForTimeout(300);
    await shot(page, "09-onboarding-keys");

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Get the models" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Finish" })).toBeVisible();
    await page.waitForTimeout(300);
    await shot(page, "10-onboarding-models");
  } finally {
    await setOnboardingComplete(true); // always restore the setup-complete state
  }
});
