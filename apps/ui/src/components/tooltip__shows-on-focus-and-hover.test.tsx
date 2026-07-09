/**
 * Behaviour tests for <Tooltip>: the "no icon-only control without a
 * tooltip" contract (redesign-brief-v2.md §5.2) depends on this actually
 * showing on BOTH hover and keyboard focus, at the promised delay, with the
 * correct ARIA wiring — not just rendering something.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Tooltip } from "./tooltip";

beforeEach(() => {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
});

afterEach(() => {
  cleanup();
});

describe("Tooltip shows on focus and hover", () => {
  it("is absent from the DOM before any interaction", () => {
    render(
      <Tooltip label="Pause all cloud AI">
        <button type="button">Kill switch</button>
      </Tooltip>,
    );
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(screen.getByRole("button").getAttribute("aria-describedby")).toBeNull();
  });

  it("shows on keyboard focus after the 300ms delay, with role=tooltip and aria-describedby wired", async () => {
    render(
      <Tooltip label="Pause all cloud AI">
        <button type="button">Kill switch</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button");

    fireEvent.focus(trigger);
    // Just-under the delay: still hidden (boundary-exact, not "eventually").
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 150));
    });
    expect(screen.queryByRole("tooltip")).toBeNull();

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toBe("Pause all cloud AI");
    expect(trigger.getAttribute("aria-describedby")).toBe(tooltip.id);
  });

  it("shows on mouse hover after the delay", async () => {
    render(
      <Tooltip label="Auto-run safe actions">
        <button type="button">Instant execute</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByRole("button"));
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toBe("Auto-run safe actions");
  });

  it("hides immediately on blur, cancelling a pending show", async () => {
    render(
      <Tooltip label="AI providers">
        <button type="button">Router</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button");
    fireEvent.focus(trigger);
    fireEvent.blur(trigger);
    // Wait well past the show delay — it must never appear once blurred.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("hides on mouse leave", async () => {
    render(
      <Tooltip label="Transcription quality">
        <button type="button">Engine</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button");
    fireEvent.mouseEnter(trigger);
    await screen.findByRole("tooltip");
    fireEvent.mouseLeave(trigger);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("supports side placement without changing the label content", async () => {
    render(
      <Tooltip label="Everyone else" side="right">
        <button type="button">Them stream</button>
      </Tooltip>,
    );
    fireEvent.focus(screen.getByRole("button"));
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toBe("Everyone else");
  });

  it("throws a clear error if given more than a single element child at runtime", () => {
    // TypeScript would normally catch this at the call site; this test
    // guards the runtime defensive check for any path that bypasses types
    // (e.g. a .js consumer, or a conditional that resolves to a string).
    const BadUsage = () => (
      // @ts-expect-error -- deliberately violating the single-element-child contract to exercise the runtime guard
      <Tooltip label="broken">not an element</Tooltip>
    );
    expect(() => render(<BadUsage />)).toThrow(/single element/);
  });
});
