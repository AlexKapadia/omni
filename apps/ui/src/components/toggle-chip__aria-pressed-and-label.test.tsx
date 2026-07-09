/**
 * Behaviour tests for <ToggleChip>: the Live capability strip
 * (redesign-brief-v2.md §5.3) depends on real toggle-button semantics
 * (aria-pressed, not colour alone) and a click that actually flips state.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ToggleChip } from "./toggle-chip";
import { AudioLines } from "lucide-react";

afterEach(() => {
  cleanup();
});

describe("ToggleChip aria-pressed and label", () => {
  it("renders the label and reflects the off state via aria-pressed=false", () => {
    render(<ToggleChip pressed={false} onPressedChange={() => undefined} label="Captions" />);
    const chip = screen.getByRole("button", { name: "Captions" });
    expect(chip.getAttribute("aria-pressed")).toBe("false");
  });

  it("reflects the on state via aria-pressed=true", () => {
    render(<ToggleChip pressed onPressedChange={() => undefined} label="Translate" />);
    expect(screen.getByRole("button", { name: "Translate" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("calls onPressedChange with the flipped value on click — off to on", () => {
    const onPressedChange = vi.fn();
    render(<ToggleChip pressed={false} onPressedChange={onPressedChange} label="Board" />);
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(onPressedChange).toHaveBeenCalledExactlyOnceWith(true);
  });

  it("calls onPressedChange with the flipped value on click — on to off", () => {
    const onPressedChange = vi.fn();
    render(<ToggleChip pressed onPressedChange={onPressedChange} label="Summary" />);
    fireEvent.click(screen.getByRole("button", { name: "Summary" }));
    expect(onPressedChange).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("never fires onPressedChange while disabled", () => {
    const onPressedChange = vi.fn();
    render(<ToggleChip pressed={false} onPressedChange={onPressedChange} label="Answers" disabled />);
    const chip = screen.getByRole("button", { name: "Answers" });
    expect((chip as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(chip);
    expect(onPressedChange).not.toHaveBeenCalled();
  });

  it("renders an aria-hidden icon when one is supplied, keeping the accessible name as the text label only", () => {
    render(<ToggleChip pressed={false} onPressedChange={() => undefined} label="Notes" icon={AudioLines} />);
    const chip = screen.getByRole("button", { name: "Notes" });
    const icon = chip.querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon?.getAttribute("aria-hidden")).toBe("true");
  });

  it("renders with no icon at all when none is supplied", () => {
    render(<ToggleChip pressed={false} onPressedChange={() => undefined} label="Notes" />);
    const chip = screen.getByRole("button", { name: "Notes" });
    expect(chip.querySelector("svg")).toBeNull();
  });
});
