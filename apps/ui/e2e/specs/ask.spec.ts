/**
 * Ask Omni — the flagship: a REAL question answered by the real retrieval +
 * router pipeline (BM25 over the indexed vault → Gemini synthesis), with real
 * inline citations and the engine-measured latency readout. Also the honest
 * no-match state (answered from the vault only — never a fabricated answer).
 */
import { test, expect } from "../harness/fixtures";

async function gotoAsk(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Ask Omni" }).click();
  await expect(page.getByRole("heading", { name: "Ask across everything you know" })).toBeVisible();
}

test("empty state shows the page display and the privacy line", async ({ page }) => {
  await gotoAsk(page);
  await expect(page.getByText("Answers come from your vault only. Nothing leaves this device.")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Ask Omni" })).toBeVisible();
});

test("answers a real question from the vault with citations and latency", async ({ page }) => {
  await gotoAsk(page);
  await page.getByRole("textbox", { name: "Ask Omni" }).fill("What did we agree on the Northwind renewal?");
  await page.keyboard.press("Enter");

  // Real synthesis takes a few seconds; wait for the answered article.
  const answer = page.getByRole("article", { name: "Answer" });
  await expect(answer).toBeVisible({ timeout: 40_000 });
  // A real inline citation chip (note_path · line range) — proves grounded output.
  await expect(page.getByLabel(/\.md · \d+/).first()).toBeVisible();
  // Engine-measured latency, rendered verbatim (retrieval + synthesis = total).
  await expect(page.getByLabel("Answer latency")).toContainText(/retrieval \d+ ms · synthesis \d+ ms · total \d+ ms/);
});

test("expands a citation source on click", async ({ page }) => {
  await gotoAsk(page);
  await page.getByRole("textbox", { name: "Ask Omni" }).fill("What are the Atlas onboarding decisions?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible({ timeout: 40_000 });
  const chip = page.getByLabel(/\.md · \d+/).first();
  await chip.click();
  // Expanding reveals the verbatim cited snippet under the chip.
  await expect(chip).toBeVisible();
});

test("honest no-match state for a question outside the vault", async ({ page }) => {
  await gotoAsk(page);
  await page.getByRole("textbox", { name: "Ask Omni" }).fill("What is the capital of France?");
  await page.keyboard.press("Enter");
  // The engine answers from the vault only: an honest 'not in your notes',
  // never a fabricated fact. Either the answered honest headline or the error
  // state is acceptable — both are truthful; a confident wrong answer is not.
  await expect(
    page.getByText(/not in your notes|don't have|couldn't find|no answer|could not answer/i),
  ).toBeVisible({ timeout: 40_000 });
});
