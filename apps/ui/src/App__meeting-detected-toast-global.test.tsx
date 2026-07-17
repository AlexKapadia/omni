/**
 * In-app meeting toast was replaced by a desktop always-on-top window.
 * Visibility + Start / Keep going wiring live in wire-meeting-toast-desktop tests.
 */
import { describe, expect, it } from "vitest";
import {
  MEETING_TOAST_KEEP_GOING_EVENT,
  MEETING_TOAST_START_EVENT,
} from "./lib/wire-meeting-toast-desktop";

describe("desktop meeting toast contract", () => {
  it("pins the start event name the shell emits to the main window", () => {
    expect(MEETING_TOAST_START_EVENT).toBe("meeting-toast-start-capture");
  });

  it("pins the keep-going event name so stop hints can re-show later", () => {
    expect(MEETING_TOAST_KEEP_GOING_EVENT).toBe("meeting-toast-keep-going");
  });
});
