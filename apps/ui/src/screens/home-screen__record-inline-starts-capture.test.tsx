/**
 * Home "Record Inline" must start Live capture (not only open dictation history).
 * "View Notes" stays on the dictation screen.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomeScreen } from "./home-screen";

afterEach(cleanup);

describe("HomeScreen Record Inline", () => {
  it("starts capture via onStartCapture; View Notes navigates to dictation", () => {
    const onNavigate = vi.fn();
    const onStartCapture = vi.fn();
    render(<HomeScreen onNavigate={onNavigate} onStartCapture={onStartCapture} />);

    fireEvent.click(screen.getByRole("button", { name: "View Notes" }));
    expect(onNavigate).toHaveBeenCalledExactlyOnceWith("dictation");
    expect(onStartCapture).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Record Inline" }));
    expect(onStartCapture).toHaveBeenCalledOnce();
    // Must not also dump the user on dictation history for the primary CTA.
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
});
