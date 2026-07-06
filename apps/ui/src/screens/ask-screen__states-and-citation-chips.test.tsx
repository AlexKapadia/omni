/**
 * State-coverage + citation-target tests for Ask Omni: empty, thinking
 * (shimmer, no spinner), answered with EXACT citation chip targets
 * (note_path + line range per the M3 §Cite contract), source detail
 * toggling, and the error state with a working retry.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AskScreen } from "./ask-screen";
import { askStore, INITIAL_ASK_STATE, type AskAnswer } from "../lib/ask-store";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);

beforeEach(() => {
  askStore.setState(INITIAL_ASK_STATE, true);
});

afterEach(cleanup);

const ANSWER: AskAnswer = {
  headline: "Northwind renewal",
  prose: [
    { text: "Priced at " },
    { text: "$84,000", strong: true, citationMarker: 1 },
    { text: " for the year." },
  ],
  citations: [
    {
      marker: 1,
      notePath: "vault/clients/northwind.md",
      lineStart: 42,
      lineEnd: 58,
      headingPath: "Northwind › Renewal 2026",
      snippet: "Renewal quote: $84,000/yr single-tenant.",
    },
  ],
};

function submitQuestion(question: string) {
  const input = screen.getByRole("textbox", { name: "Ask Omni" });
  fireEvent.change(input, { target: { value: question } });
  fireEvent.submit(input.closest("form")!);
}

describe("AskScreen states", () => {
  it("EMPTY: page display, ghost input and the privacy line", () => {
    render(<AskScreen provider={{ answer: () => Promise.resolve(ANSWER) }} />);
    expect(screen.getByText("Ask across everything you know")).toBeTruthy();
    expect(
      screen.getByText("Answers come from your vault only. Nothing leaves this device."),
    ).toBeTruthy();
  });

  it("THINKING: quoted question + shimmer, and never a stale answer", () => {
    // Never-resolving provider holds the thinking state open for assertion.
    render(<AskScreen provider={{ answer: () => new Promise(() => undefined) }} />);
    act(() => submitQuestion("what is the renewal price?"));
    expect(screen.getByText("“what is the renewal price?”")).toBeTruthy();
    expect(screen.getByRole("status", { name: "Loading" })).toBeTruthy();
    expect(screen.queryByText("Northwind renewal")).toBeNull();
  });

  it("ANSWERED: prose with strong facts, inline markers and exact chip targets", async () => {
    render(<AskScreen provider={{ answer: () => Promise.resolve(ANSWER) }} />);
    await act(async () => submitQuestion("renewal?"));
    expect(screen.getByText("Northwind renewal")).toBeTruthy();
    expect(screen.getByText("$84,000")).toBeTruthy();
    // Citation chip target correctness: accessible name IS path + line range.
    const chip = screen.getByRole("button", { name: "vault/clients/northwind.md · L42–58" });
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    // Clicking reveals the exact source detail; clicking again hides it.
    fireEvent.click(chip);
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Northwind › Renewal 2026")).toBeTruthy();
    expect(screen.getByText("“Renewal quote: $84,000/yr single-tenant.”")).toBeTruthy();
    fireEvent.click(chip);
    expect(screen.queryByText("Northwind › Renewal 2026")).toBeNull();
  });

  it("ERROR: honest copy, real message, and Try again actually retries", async () => {
    let attempts = 0;
    const flaky = {
      answer: () => {
        attempts += 1;
        return attempts === 1
          ? Promise.reject(new Error("index is still building"))
          : Promise.resolve(ANSWER);
      },
    };
    render(<AskScreen provider={flaky} />);
    await act(async () => submitQuestion("renewal?"));
    expect(screen.getByText("Could not answer that.")).toBeTruthy();
    expect(screen.getByText("index is still building")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    });
    expect(screen.getByText("Northwind renewal")).toBeTruthy();
  });
});
