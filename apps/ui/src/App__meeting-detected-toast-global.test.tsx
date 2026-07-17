/**
 * In-app meeting toast was replaced by a desktop always-on-top window.
 * Visibility + Start wiring live in wire-meeting-toast-desktop tests.
 */
import { describe, expect, it } from "vitest";
import { MEETING_TOAST_START_EVENT } from "./lib/wire-meeting-toast-desktop";

describe("desktop meeting toast contract", () => {
  it("pins the start event name the shell emits to the main window", () => {
    expect(MEETING_TOAST_START_EVENT).toBe("meeting-toast-start-capture");
  });
});
