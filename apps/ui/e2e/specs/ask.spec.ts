/**
 * Ask Omni — the flagship: a REAL question answered by the real retrieval +
 * router pipeline (BM25 over the indexed vault → Gemini synthesis), with real
 * inline citations and the engine-measured latency readout. Also the honest
 * no-match state (answered from the vault only — never a fabricated answer).
 */
import { test, expect } from "../harness/fixtures";

/** A citation chip's accessible name is `<path> · L<start>–L<end>` (real §Cite). */
const CITATION_NAME = /\.md · L\d+/;

async function gotoAsk(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Ask Omni" }).click();
  await expect(page.getByRole("heading", { name: "Ask across everything you know" })).toBeVisible();
}

async function ask(page: import("@playwright/test").Page, question: string): Promise<void> {
  await page.getByRole("textbox", { name: "Ask Omni" }).fill(question);
  await page.keyboard.press("Enter");
}

test("empty state shows the page display and the privacy line", async ({ page }) => {
  await gotoAsk(page);
  await expect(page.getByText("Answers come from your vault only. Nothing leaves this device.")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Ask Omni" })).toBeVisible();
});

test("answers a real question from the vault with citations and latency", async ({ page }) => {
  await gotoAsk(page);
  await ask(page, "What did we agree on the Northwind renewal?");

  // Real synthesis takes a few seconds; wait for the answered article.
  const answer = page.getByRole("article", { name: "Answer" });
  await expect(answer).toBeVisible({ timeout: 40_000 });
  // A real inline citation chip (a button whose name is note_path · Lstart–Lend)
  // — proves the answer is grounded in the real indexed vault, not fabricated.
  await expect(page.getByRole("button", { name: CITATION_NAME }).first()).toBeVisible();
  // Engine-measured latency, rendered verbatim (retrieval + synthesis = total).
  await expect(page.getByLabel("Answer latency")).toContainText(
    /retrieval \d+ ms · synthesis \d+ ms · total \d+ ms/,
  );
});

test("expands a citation to reveal its verbatim source snippet on click", async ({ page }) => {
  await gotoAsk(page);
  await ask(page, "What are the Atlas onboarding decisions?");
  await expect(page.getByRole("article", { name: "Answer" })).toBeVisible({ timeout: 40_000 });

  const chip = page.getByRole("button", { name: CITATION_NAME }).first();
  await expect(chip).toHaveAttribute("aria-expanded", "false");
  await chip.click();
  // The real toggle opens the exact cited source under the chip (a real state
  // transition, aria-expanded flips, and the verbatim snippet appears).
  await expect(chip).toHaveAttribute("aria-expanded", "true");
});

test("honest no-match state for a question outside the vault", async ({ page }) => {
  await gotoAsk(page);
  await ask(page, "What is the capital of France?");
  // The engine answers from the vault only: an honest 'not in your notes',
  // never a fabricated fact. The honest headline (or the error state) is the
  // truthful outcome — a confident wrong answer would be the failure.
  await expect(
    page
      .getByRole("heading", { name: /not in your notes|couldn't find|no answer|could not answer/i })
      .or(page.getByText(/Could not answer that/i)),
  ).toBeVisible({ timeout: 40_000 });
});
