import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DictationHistoryScreen } from "./dictation-history-screen";

vi.mock("../lib/setup-settings-transport", () => ({
  requestSetupCommand: vi.fn(),
}));

vi.mock("../lib/live-engine-socket", () => ({
  subscribeToEngineFrames: vi.fn(() => () => undefined),
  sendEngineCommand: vi.fn(() => true),
}));

import { requestSetupCommand } from "../lib/setup-settings-transport";
import { sendEngineCommand, subscribeToEngineFrames } from "../lib/live-engine-socket";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DictationHistoryScreen", () => {
  it("subscribes to engine frames on mount even when not recording", async () => {
    vi.mocked(requestSetupCommand).mockResolvedValue({ entries: [] });
    render(<DictationHistoryScreen />);
    await waitFor(() => {
      expect(subscribeToEngineFrames).toHaveBeenCalled();
    });
  });

  it("loads and displays dictation entries", async () => {
    vi.mocked(requestSetupCommand).mockResolvedValue({
      entries: [
        {
          id: 1,
          created_at: "2026-07-08T10:00:00+00:00",
          mode: "inject",
          raw_text: "hello world",
          cleaned_text: "Hello world.",
          note_title: null,
        },
      ],
    });
    render(<DictationHistoryScreen />);
    await waitFor(() => {
      expect(screen.getByText("Hello world.")).toBeTruthy();
    });
    expect(requestSetupCommand).toHaveBeenCalledWith("dictation.history.list", {
      limit: 100,
    });
  });

  it("EMPTY: teaches the hotkey when there are zero entries", async () => {
    vi.mocked(requestSetupCommand).mockResolvedValue({ entries: [] });
    render(<DictationHistoryScreen />);
    const empty = await screen.findByRole("status", { name: "No voice notes yet" });
    expect(empty).toBeTruthy();
    expect(screen.getByText("No voice notes yet")).toBeTruthy();
    expect(screen.getByText(/Hold F9 anywhere to capture a thought/)).toBeTruthy();
    // No list row is rendered when the history is genuinely empty.
    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("Cancel sends dictation.cancel and stops recording without dictation.end", async () => {
    vi.mocked(requestSetupCommand).mockResolvedValue({ entries: [] });
    vi.mocked(sendEngineCommand).mockReturnValue(true);
    // getUserMedia is used for the waveform preview only.
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(new Error("no mic in test")),
      },
    });

    render(<DictationHistoryScreen />);
    fireEvent.click(await screen.findByRole("button", { name: /Record Note/i }));
    await waitFor(() => {
      expect(sendEngineCommand).toHaveBeenCalledWith("dictation.begin");
    });
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(sendEngineCommand).toHaveBeenCalledWith("dictation.cancel");
    expect(sendEngineCommand).not.toHaveBeenCalledWith(
      "dictation.end",
      expect.anything(),
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Record Note/i })).toBeTruthy();
    });
  });

  it("Done & Save checks sendEngineCommand and surfaces an error on failure", async () => {
    vi.mocked(requestSetupCommand).mockResolvedValue({ entries: [] });
    vi.mocked(sendEngineCommand)
      .mockReturnValueOnce(true) // begin
      .mockReturnValueOnce(false); // end fails
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(new Error("no mic in test")),
      },
    });

    render(<DictationHistoryScreen />);
    fireEvent.click(await screen.findByRole("button", { name: /Record Note/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Done & Save/i })).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: /Done & Save/i }));
    expect(sendEngineCommand).toHaveBeenCalledWith("dictation.end", {
      inject_requested: false,
    });
    await waitFor(() => {
      expect(screen.getByText(/could not save the voice note/i)).toBeTruthy();
    });
  });
});
