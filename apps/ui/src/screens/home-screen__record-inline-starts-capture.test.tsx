/**
 * Home "Record Inline" opens the dictation inline recorder (not Live capture).
 * "View Notes" stays on the dictation screen.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomeScreen } from "./home-screen";

afterEach(cleanup);

describe("HomeScreen Record Inline", () => {
  it("triggers onRecordInline for the inline dictation flow; View Notes navigates", () => {
    const onNavigate = vi.fn();
    const onStartCapture = vi.fn();
    const onRecordInline = vi.fn();
    render(
      <HomeScreen
        onNavigate={onNavigate}
        onStartCapture={onStartCapture}
        onRecordInline={onRecordInline}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "View Notes" }));
    expect(onNavigate).toHaveBeenCalledExactlyOnceWith("dictation");
    expect(onStartCapture).not.toHaveBeenCalled();
    expect(onRecordInline).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Record Inline" }));
    expect(onRecordInline).toHaveBeenCalledOnce();
    // Must not start a full meeting capture for the voice-replacement CTA.
    expect(onStartCapture).not.toHaveBeenCalled();
  });

  it("falls back to navigating to dictation when onRecordInline is omitted", () => {
    const onNavigate = vi.fn();
    const onStartCapture = vi.fn();
    render(<HomeScreen onNavigate={onNavigate} onStartCapture={onStartCapture} />);

    fireEvent.click(screen.getByRole("button", { name: "Record Inline" }));
    expect(onNavigate).toHaveBeenCalledWith("dictation");
    expect(onStartCapture).not.toHaveBeenCalled();
  });
});
