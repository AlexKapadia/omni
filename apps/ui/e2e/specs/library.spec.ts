/**
 * Library screen — real seeded meetings over meetings.list, the live search
 * filter, and the detail pane over meeting.get. Every assertion is a real
 * state transition against the engine, not a render check. Also proves the
 * cold-boot recovery: the Library is the default screen, so it mounts before
 * the engine socket opens; the app re-loads on connect and the real rows show.
 */
import { test, expect } from "../harness/fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Meetings", level: 1 })).toBeVisible();
  // The rows arrive once the engine connection is up (cold-boot recovery) —
  // wait for the first real row rather than asserting on a boot-race snapshot.
  await expect(page.getByRole("button", { name: "Open Northwind Renewal" })).toBeVisible({
    timeout: 20_000,
  });
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

test("opening a meeting shows its real enhanced notes, actions and transcript", async ({ page }) => {
  await page.getByRole("button", { name: "Open Northwind Renewal" }).click();
  // Role-scoped (getByLabel("Meeting detail") also matches "Close meeting detail").
  const pane = page.getByRole("complementary", { name: "Meeting detail" });
  await expect(pane).toBeVisible();

  // Real enhanced-notes content the seed wrote (proves meeting.get round-trip).
  await expect(pane.getByText(/24-month term/)).toBeVisible();

  // The approval rack is scoped to this meeting; with no extracted cards it
  // shows its honest empty state — a real answer, never a blank.
  await expect(pane.getByRole("region", { name: "Approval cards" })).toBeVisible();
  await expect(pane.getByText(/Nothing to approve\./)).toBeVisible();

  // The transcript is a collapsed disclosure — expand it to reveal real lines.
  await pane.getByText(/\d+ segments — click to expand/).click();
  await expect(pane.getByText(/twelve percent uplift/i)).toBeVisible();

  await page.getByRole("button", { name: "Close meeting detail" }).click();
  await expect(page.getByRole("complementary", { name: "Meeting detail" })).toBeHidden();
});
