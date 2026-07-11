import { describe, expect, it, vi } from "vitest";
import { askAboutMeeting } from "./meeting-chat-repository";
import type { AskQueryTransport } from "./engine-ask-answer-provider";

const VALID_ASK_REPLY = {
  headline: "Answer",
  answer_md: "Friday is the deadline.",
  no_answer: false,
  citations: [],
  latency: { retrieval_ms: 1, synthesis_ms: 2, total_ms: 3 },
};

describe("askAboutMeeting", () => {
  it("sends meeting_id via ask transport (ask.answer path)", async () => {
    const request = vi.fn().mockResolvedValue(VALID_ASK_REPLY);
    const transport: AskQueryTransport = { request };
    const answer = await askAboutMeeting("m-42", "When is the deadline?", transport);
    expect(request).toHaveBeenCalledWith("ask.query", {
      query: "When is the deadline?",
      meeting_id: "m-42",
    });
    expect(answer.headline).toBe("Answer");
    expect(answer.prose[0]?.text).toContain("Friday");
  });

  it("rejects malformed engine payloads", async () => {
    const transport: AskQueryTransport = {
      request: vi.fn().mockResolvedValue({ headline: 1 }),
    };
    await expect(askAboutMeeting("m-1", "hi", transport)).rejects.toThrow(/could not read/i);
  });

  it("surfaces transport errors (e.g. unexpected ok reply name)", async () => {
    const transport: AskQueryTransport = {
      request: vi.fn().mockRejectedValue(new Error("engine replied ok")),
    };
    await expect(askAboutMeeting("m-1", "hi", transport)).rejects.toThrow(/engine replied ok/i);
  });
});
