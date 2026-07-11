/**
 * View tests for the dictation pill — the rehaul's user-facing surface:
 * sentence-case chips (Note / Command / Paste, never NOTE/COMMAND/INSERT), the
 * locked "Still listening" padlock affordance, and the latency strip HIDDEN by
 * default (power-user opt-in only). Drives the real reducer through the store,
 * so every assertion reflects a genuine pill state, not a prop.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

const sendEngineCommand = vi.hoisted(() => vi.fn(() => true));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ hide: vi.fn().mockResolvedValue(undefined) }),
}));

vi.mock("../lib/live-engine-socket", () => ({
  sendEngineCommand: (...args: unknown[]) => sendEngineCommand(...args),
}));

import {
  applyCardsListReply,
  approvalCardsStore,
  clearApprovalCards,
} from "../lib/approval-cards-store";
import type { DictationFinalPayload } from "./dictation-events-protocol";
import { DictationPillView } from "./dictation-pill-view";
import { dictationPillStore, dispatchPillEvent } from "./dictation-pill-store";
import { IDLE_PILL_STATE, type DictationPillEvent } from "./dictation-pill-state";

beforeEach(() => {
  dictationPillStore.setState(IDLE_PILL_STATE, true);
  clearApprovalCards(approvalCardsStore);
  sendEngineCommand.mockClear();
  try {
    window.localStorage.clear();
  } catch {
    /* jsdom always has localStorage; guard is belt-and-braces */
  }
});

afterEach(cleanup);

function drive(events: readonly DictationPillEvent[]): void {
  act(() => {
    for (const event of events) dispatchPillEvent(dictationPillStore, event);
  });
}

const NOTE_FINAL: DictationFinalPayload = {
  mode: "note",
  text: "buy milk",
  cleaned_text: "Buy milk.",
  cleanup_source: "model",
  cleanup_latency_ms: 412,
  flush_ms: 96,
};

describe("idle hold hint", () => {
  it("defaults to Hold F9", () => {
    render(<DictationPillView />);
    expect(screen.getByText("Hold F9")).toBeTruthy();
  });

  it("shows the configured holdLabel", () => {
    render(<DictationPillView holdLabel="Hold Ctrl+Shift+F8" />);
    expect(screen.getByText("Hold Ctrl+Shift+F8")).toBeTruthy();
    expect(screen.queryByText("Hold F9")).toBeNull();
  });
});

describe("mode chips are sentence case", () => {
  it("idle shows a ghost 'Note' chip (not NOTE)", () => {
    render(<DictationPillView />);
    expect(screen.getByText("Note")).toBeTruthy();
    expect(screen.queryByText("NOTE")).toBeNull();
  });

  it("a heard wake word flips the chip to 'Command'", () => {
    render(<DictationPillView />);
    drive([
      { type: "hold-pressed", atMs: 0 },
      { type: "partial", text: "Omni, schedule lunch" },
    ]);
    expect(screen.getByText("Command")).toBeTruthy();
    expect(screen.queryByText("COMMAND")).toBeNull();
  });

  it("inject-eligible arms a clickable 'Paste' chip (not INSERT)", () => {
    render(<DictationPillView />);
    drive([{ type: "hold-pressed", atMs: 0, injectEligible: true }]);
    expect(screen.getByRole("button", { name: "Paste" })).toBeTruthy();
    expect(screen.queryByText("INSERT")).toBeNull();
  });
});

describe("locked hands-free affordance", () => {
  it("shows a padlock + 'Still listening' once the lock engages", () => {
    render(<DictationPillView />);
    drive([
      { type: "hold-pressed", atMs: 0 },
      { type: "lock-engaged" },
    ]);
    expect(screen.getByText("Still listening")).toBeTruthy();
    expect(screen.getByTestId("pill-lock-icon")).toBeTruthy();
    expect(screen.getByLabelText("Locked — still listening")).toBeTruthy();
  });
});

describe("latency strip is hidden by default", () => {
  const toNoteResult: readonly DictationPillEvent[] = [
    { type: "hold-pressed", atMs: 0 },
    { type: "hold-released" },
    { type: "final", payload: NOTE_FINAL, totalMs: 900 },
  ];

  it("a note result shows NO stt/clean/total strip by default", () => {
    render(<DictationPillView />);
    drive(toNoteResult);
    expect(screen.getByText("Note saved")).toBeTruthy();
    expect(screen.queryByText(/stt 96 ms/)).toBeNull();
    expect(screen.queryByText(/total 900 ms/)).toBeNull();
  });

  it("the debug opt-in reveals the REAL measured strip", () => {
    window.localStorage.setItem("omni.pill.debugLatency", "true");
    render(<DictationPillView />);
    drive(toNoteResult);
    expect(screen.getByText(/stt 96 ms · clean 412 ms · total 900 ms/)).toBeTruthy();
  });
});

describe("command result Approve next to Dismiss", () => {
  const COMMAND_FINAL: DictationFinalPayload = {
    mode: "command",
    text: "schedule lunch with Tom",
    intent: {
      intent_type: "create_event",
      fields: { title: "Lunch with Tom" },
      confidence: 0.92,
    },
  };

  it("Approve sends card.approve for the pending dictation card", () => {
    applyCardsListReply(approvalCardsStore, {
      cards: [
        {
          id: 42,
          meeting_id: null,
          source: "dictation",
          card_type: "create_event",
          status: "pending",
          payload: { title: "Lunch with Tom" },
          preview_lines: ["Event: Lunch with Tom"],
          created_at: "2026-07-06T12:00:00+00:00",
          decided_at: null,
          executed_at: null,
          error: null,
          result_summary: null,
        },
      ],
    });
    render(<DictationPillView />);
    drive([
      { type: "hold-pressed", atMs: 0 },
      { type: "hold-released" },
      { type: "final", payload: COMMAND_FINAL },
    ]);
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(sendEngineCommand).toHaveBeenCalledWith("card.approve", { id: 42 });
  });
});
