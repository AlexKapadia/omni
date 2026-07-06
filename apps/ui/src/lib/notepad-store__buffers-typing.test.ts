/**
 * Tests for the notepad buffer: no keystroke may ever be lost — including
 * across meeting re-binds of the SAME meeting (screen switches, StrictMode
 * remounts) — while a genuinely new meeting starts on a fresh page.
 */
import { describe, expect, it } from "vitest";
import { bindNotepadToMeeting, createNotepadStore, setNotepadText } from "./notepad-store";

describe("notepad buffer", () => {
  it("stores text verbatim, including newlines, unicode and markdown", () => {
    const store = createNotepadStore();
    const text = "- follow up\n\n**bold** · em-dash — ✓\n\ttabbed";
    setNotepadText(store, text);
    expect(store.getState().text).toBe(text);
  });

  it("survives a very large buffer exactly (100k chars, no truncation)", () => {
    const store = createNotepadStore();
    const big = "x".repeat(100_000) + "END";
    setNotepadText(store, big);
    expect(store.getState().text).toHaveLength(100_003);
    expect(store.getState().text.endsWith("END")).toBe(true);
  });

  it("re-binding the SAME meeting keeps the buffer (remount safety)", () => {
    const store = createNotepadStore();
    bindNotepadToMeeting(store, "m1");
    setNotepadText(store, "do not lose me");
    bindNotepadToMeeting(store, "m1"); // StrictMode double-mount / screen switch
    expect(store.getState().text).toBe("do not lose me");
  });

  it("binding a DIFFERENT meeting starts a fresh page", () => {
    const store = createNotepadStore();
    bindNotepadToMeeting(store, "m1");
    setNotepadText(store, "old meeting notes");
    bindNotepadToMeeting(store, "m2");
    expect(store.getState().text).toBe("");
    expect(store.getState().meetingId).toBe("m2");
  });
});
