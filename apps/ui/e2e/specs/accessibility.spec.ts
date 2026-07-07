/**
 * Accessibility — automated WCAG 2.2 AA checks (axe-core) on the real running
 * app across its primary screens, with real engine data loaded. We fail on any
 * serious/critical violation; this is the automated half of the UI a11y gate
 * (manual keyboard / focus / screen-reader checks live in the DoD checklist).
 *
 * `color-contrast` IS enforced. Secondary/meta text uses --ink-secondary
 * (#6E6E6E — 5.10:1 on the #FFFFFF canvas, 4.76:1 on the #F7F7F7 surface, both
 * clearing the 4.5:1 AA threshold) rather than the decorative --grey-400
 * (#A3A3A3 ≈ 2.5:1, kept only for borders/dividers/dots that carry no text).
 * The strictly-monochrome look is preserved while every text run meets AA, so
 * this gate now guards contrast alongside roles, names, labels, ARIA and
 * structure — no rules are disabled.
 */
import { test, expect } from "../harness/fixtures";
import AxeBuilder from "@axe-core/playwright";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Run axe on the current page and return only serious/critical violations.
 *  color-contrast is enforced (see header) — no rules are disabled. */
async function seriousViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page })
    .withTags(WCAG_TAGS)
    .analyze();
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

test("Library home has no serious/critical WCAG 2.2 AA violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Open Northwind Renewal" })).toBeVisible({ timeout: 20_000 });
  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations.map((v) => v.id), null, 2)).toEqual([]);
});

test("Settings has no serious/critical WCAG 2.2 AA violations", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("table", { name: "Routing policy" })).toBeVisible({ timeout: 20_000 });
  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations.map((v) => v.id), null, 2)).toEqual([]);
});

test("Ask (answered) has no serious/critical WCAG 2.2 AA violations", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Ask Omni" }).click();
  await page.getByRole("textbox", { name: "Ask Omni" }).fill("What did we agree on the Northwind renewal?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible({ timeout: 40_000 });
  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations.map((v) => v.id), null, 2)).toEqual([]);
});
