/**
 * Library screen — real seeded meetings over meetings.list, the live search
 * filter, and the detail pane over meeting.get. Every assertion is a real
 * state transition against the engine, not a render check.
 */
import { test, expect } from "../harness/fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();
});

test("lists the real seeded meetings with a summary line", async ({ page }) => {
  // Three synthetic finalized meetings were seeded into the real DB.
  await expect(page.getByRole("button", { name: "Open Northwind Renewal" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Atlas Onboarding Sync" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Quarterly Planning" })).toBeVisible();
  // The header count is derived from the real rows.
  await expect(page.getByText(/\d+ meetings ·/)).toBeVisible();
});

test("search filters the list live and shows an honest no-match state", async ({ page }) => {
  const search = page.getByRole("searchbox", { name: "Search meetings" });
  await search.fill("northwind");
  await expect(page.getByRole("button", { name: "Open Northwind Renewal" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Atlas Onboarding Sync" })).toBeHidden();

  await search.fill("nothing-matches-this-xyz");
  await expect(page.getByText(/No meetings match/)).toBeVisible();

  await search.fill("");
  await expect(page.getByRole("button", { name: "Open Atlas Onboarding Sync" })).toBeVisible();
});

test("opening a meeting shows its real enhanced notes and transcript", async ({ page }) => {
  await page.getByRole("button", { name: "Open Northwind Renewal" }).click();
  const pane = page.getByRole("region", { name: "Meeting detail" }).or(
    page.getByLabel("Meeting detail"),
  );
  await expect(pane.first()).toBeVisible();
  // Real enhanced-notes content the seed wrote (proves meeting.get round-trip).
  await expect(page.getByText(/24-month term/)).toBeVisible();
  // A real transcript line from the seeded segments.
  await expect(page.getByText(/twelve percent uplift/i)).toBeVisible();

  await page.getByRole("button", { name: "Close meeting detail" }).click();
  await expect(page.getByLabel("Meeting detail")).toBeHidden();
});
