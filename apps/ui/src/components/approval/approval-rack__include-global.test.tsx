/**
 * Global dictation cards (meetingId=null) must surface when includeGlobal is set.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  applyCardsListReply,
  approvalCardsStore,
  clearApprovalCards,
} from "../../lib/approval-cards-store";
import { ApprovalRack } from "./approval-rack";

vi.mock("../../lib/live-engine-socket", () => ({
  sendEngineCommand: () => true,
}));

beforeEach(() => {
  clearApprovalCards(approvalCardsStore);
  applyCardsListReply(approvalCardsStore, {
    cards: [
      {
        id: 1,
        meeting_id: "m-1",
        source: "extraction",
        card_type: "create_event",
        status: "pending",
        payload: { title: "Meeting card" },
        preview_lines: ["Event: Meeting card"],
        created_at: "2026-07-06T12:00:00+00:00",
        decided_at: null,
        executed_at: null,
        error: null,
        result_summary: null,
      },
      {
        id: 2,
        meeting_id: null,
        source: "dictation",
        card_type: "create_event",
        status: "pending",
        payload: { title: "Dictation card" },
        preview_lines: ["Event: Dictation card"],
        created_at: "2026-07-06T12:01:00+00:00",
        decided_at: null,
        executed_at: null,
        error: null,
        result_summary: null,
      },
    ],
  });
});

afterEach(cleanup);

describe("ApprovalRack includeGlobal", () => {
  it("with meetingId only shows that meeting's cards (hides global)", () => {
    render(<ApprovalRack meetingId="m-1" />);
    expect(screen.getByText("Event: Meeting card")).toBeTruthy();
    expect(screen.queryByText("Event: Dictation card")).toBeNull();
  });

  it("with includeGlobal shows meeting cards plus meetingId=null cards", () => {
    render(<ApprovalRack meetingId="m-1" includeGlobal />);
    expect(screen.getByText("Event: Meeting card")).toBeTruthy();
    expect(screen.getByText("Event: Dictation card")).toBeTruthy();
  });

  it("meetingId=null with includeGlobal shows only global cards", () => {
    render(<ApprovalRack meetingId={null} includeGlobal />);
    expect(screen.getByText("Event: Dictation card")).toBeTruthy();
    expect(screen.queryByText("Event: Meeting card")).toBeNull();
  });
});
