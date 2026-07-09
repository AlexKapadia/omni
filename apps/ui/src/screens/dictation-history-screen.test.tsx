import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { DictationHistoryScreen } from "./dictation-history-screen";

vi.mock("../lib/setup-settings-transport", () => ({
  requestSetupCommand: vi.fn(),
}));

import { requestSetupCommand } from "../lib/setup-settings-transport";

afterEach(cleanup);

describe("DictationHistoryScreen", () => {
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
});
