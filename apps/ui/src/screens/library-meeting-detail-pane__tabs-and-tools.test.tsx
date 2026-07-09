/**
 * Library detail pane — Meetily parity tabs: Chat, Tools (copy, search/replace, md export).
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { FinalizeOutcome, MeetingDetail } from "../lib/meetings-live-repository";
import {
  INITIAL_MEETINGS_DETAIL_STATE,
  meetingsDetailStore,
  openMeetingDetail,
} from "../lib/meetings-detail-store";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";
import { LibraryMeetingDetailPane } from "./library-meeting-detail-pane";

vi.mock("../lib/copy-to-clipboard", () => ({
  copyTextToClipboard: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../lib/meeting-export", () => ({
  downloadMeetingExport: vi.fn().mockResolvedValue({
    content: "# Full meeting",
    encoding: "text",
    mime: "text/markdown",
    filename: "Vendor sync.md",
  }),
  triggerBrowserDownload: vi.fn(),
}));

vi.mock("../lib/meeting-text-replace-repository", () => ({
  replaceMeetingText: vi.fn().mockResolvedValue({ transcriptSegments: 1, enhancedNotes: 0 }),
}));

vi.mock("../lib/meeting-chat-repository", () => ({
  askAboutMeeting: vi.fn().mockResolvedValue({
    headline: "Answer",
    prose: [{ text: "Friday." }],
    citations: [],
    latency: { retrievalMs: 0, synthesisMs: 1, totalMs: 1 },
  }),
}));

import { copyTextToClipboard } from "../lib/copy-to-clipboard";
import { replaceMeetingText } from "../lib/meeting-text-replace-repository";
import { askAboutMeeting } from "../lib/meeting-chat-repository";
import { downloadMeetingExport } from "../lib/meeting-export";

beforeAll(installJsdomMatchMediaShim);

beforeEach(() => {
  meetingsDetailStore.setState(INITIAL_MEETINGS_DETAIL_STATE, true);
  vi.clearAllMocks();
});

afterEach(cleanup);

const DETAIL: MeetingDetail = {
  id: "m-1",
  title: "Vendor sync",
  startIso: "2026-07-06T10:00:00+00:00",
  endedIso: "2026-07-06T10:30:00+00:00",
  durationMin: 30,
  finalized: true,
  notePath: "Meetings/2026-07-06 Vendor sync.md",
  notesText: "notes",
  enhancedNotesMd: "## Summary\nRenewal agreed.",
  extraction: null,
  transcript: [
    { segmentId: "s1", stream: "them", speakerLabel: "Speaker 1", text: "hello", tStart: 0, tEnd: 1 },
  ],
};

const OUTCOME: FinalizeOutcome = {
  notePath: "Meetings/x.md",
  enhanceOk: true,
  extractionOk: true,
  warnings: [],
};

function renderReady() {
  openMeetingDetail(meetingsDetailStore, "m-1");
  return render(
    <LibraryMeetingDetailPane
      meetingId="m-1"
      loadDetail={() => Promise.resolve(DETAIL)}
      finalizeMeeting={() => Promise.resolve(OUTCOME)}
      onFinalized={() => undefined}
    />,
  );
}

describe("library detail Meetily parity tabs", () => {
  it("shows Summary, Transcript, Chat, and Export tabs", async () => {
    await act(async () => {
      renderReady();
    });
    expect(screen.getByRole("button", { name: "Summary" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Transcript" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Chat" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Export" })).toBeTruthy();
  });

  it("Chat tab asks about this meeting", async () => {
    await act(async () => {
      renderReady();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Chat" }));
    });
    const input = screen.getByLabelText("Ask about this meeting");
    fireEvent.change(input, { target: { value: "What was agreed?" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    });
    expect(askAboutMeeting).toHaveBeenCalledWith("m-1", "What was agreed?");
    expect(await screen.findByText("Friday.")).toBeTruthy();
  });

  it("Export tab copies transcript and runs search/replace", async () => {
    await act(async () => {
      renderReady();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy transcript" }));
    });
    expect(copyTextToClipboard).toHaveBeenCalledWith("Speaker 1: hello");

    fireEvent.change(screen.getByLabelText("Find"), { target: { value: "hello" } });
    fireEvent.change(screen.getByLabelText("Replace with"), { target: { value: "hi" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Replace all" }));
    });
    expect(replaceMeetingText).toHaveBeenCalledWith("m-1", "hello", "hi", "both");
  });

  it("Export tab offers MD download", async () => {
    await act(async () => {
      renderReady();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Download MD" }));
    });
    expect(downloadMeetingExport).toHaveBeenCalledWith("m-1", "md", "Vendor sync");
  });
});
