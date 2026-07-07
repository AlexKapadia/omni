# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: nav.spec.ts >> shell + navigation >> boots into the main shell and navigates every section
- Location: specs\nav.spec.ts:10:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: 'Library', level: 1 })
Expected: visible
Timeout: 15000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 15000ms
  - waiting for getByRole('heading', { name: 'Library', level: 1 })

```

```yaml
- banner:
  - link "Revolut Prep home":
    - /url: "#/dashboard"
    - text: Revolut Prep
  - navigation "Primary":
    - link "Dashboard":
      - /url: "#/dashboard"
    - link "Path":
      - /url: "#/path"
    - link "Review":
      - /url: "#/flashcards"
    - link "Search":
      - /url: "#/search"
    - link "Settings":
      - /url: "#/settings"
  - text: 0 1 LEVEL 1 0 / 50 XP
- main:
  - heading "Good morning" [level=1]
  - paragraph: 50 XP to go to hit today’s goal.
  - text: Continue learning The 2008 crisis and the failure of the tripartite system Unit 1 · Lesson 1 of 4 · The UK financial system and regulatory architecture
  - button "Resume →"
  - img
  - text: 0% Daily goal 0 / 50 XP today 0 Day streak Freeze ready Capstone tracker 0 / 5 complete
  - button "1 Consumer Duty fair-value assessment for a Revolut product"
  - button "2 Operational resilience impact-tolerance mapping"
  - button "3 APP-fraud control narrative"
  - button "4 Responsible-lending affordability walkthrough"
  - button "5 A Revolut Core strategy memo"
  - paragraph: Tap a task to mark it done as you complete each applied brief.
  - button "Open capstone briefs →"
  - text: Due today 0 You are all caught up
  - button "Browse cards →"
  - text: 1 Level 1 50 XP to level 2 Your stats 0 / 399 Lessons completed 37 Total modules 0m Study time 0% Average accuracy
```

# Test source

```ts
  1  | /**
  2  |  * Navigation + shell smoke: the REAL app boots past the setup gate into the
  3  |  * main shell (proving setup.status came back complete from the real engine),
  4  |  * every nav-rail row switches the active screen, and the status footer shows
  5  |  * the live engine state. This is also the pipeline smoke for the whole suite.
  6  |  */
  7  | import { test, expect } from "../harness/fixtures";
  8  | 
  9  | test.describe("shell + navigation", () => {
  10 |   test("boots into the main shell and navigates every section", async ({ page }) => {
  11 |     await page.goto("/");
  12 | 
  13 |     // Past the boot gate: the primary nav rail is the main shell (not the wizard).
  14 |     const nav = page.getByRole("navigation", { name: "Primary" });
  15 |     await expect(nav).toBeVisible();
> 16 |     await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();
     |                                                                            ^ Error: expect(locator).toBeVisible() failed
  17 | 
  18 |     // Every rail row fires its real state transition (aria-current tracks it).
  19 |     for (const [label, heading] of [
  20 |       ["Live meeting", "Live meeting"],
  21 |       ["Ask Omni", "Ask across everything you know"],
  22 |       ["Settings", "Settings"],
  23 |       ["Library", "Library"],
  24 |     ] as const) {
  25 |       await nav.getByRole("button", { name: label }).click();
  26 |       await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  27 |       await expect(nav.getByRole("button", { name: label })).toHaveAttribute(
  28 |         "aria-current",
  29 |         "page",
  30 |       );
  31 |     }
  32 | 
  33 |     // Naomi renders its live canvas (real WebGL/canvas2d, not an image).
  34 |     await nav.getByRole("button", { name: "Naomi" }).click();
  35 |     await expect(page.getByTestId("naomi-pool-canvas")).toBeVisible();
  36 |   });
  37 | 
  38 |   test("status footer reflects the live engine connection", async ({ page }) => {
  39 |     await page.goto("/");
  40 |     const footer = page.getByLabel("Engine status");
  41 |     await expect(footer).toBeVisible();
  42 |     // The engine is genuinely up, so a real heartbeat must flip the status dot
  43 |     // to "connected" (an open socket alone is not enough — protocol.ts gates it).
  44 |     await expect(footer.locator('[data-status="connected"]')).toBeVisible({ timeout: 20_000 });
  45 |     // A real ping/pong round-trip renders a numeric latency (never the "— ms" idle).
  46 |     await expect(page.getByLabel("Engine round-trip latency")).toContainText(/\d+\s*ms/);
  47 |   });
  48 | });
  49 | 
```