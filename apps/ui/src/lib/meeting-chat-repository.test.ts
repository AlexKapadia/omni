import { describe, expect, it, vi } from "vitest";
import { askAboutMeeting } from "./meeting-chat-repository";

vi.mock("./meetings-live-repository", () => ({
  requestEngineReply: vi.fn(),
}));

import { requestEngineReply } from "./meetings-live-repository";

const VALID_ASK_REPLY = {
  headline: "Answer",
  answer_md: "Friday is the deadline.",
  no_answer: false,
  citations: [],
  latency: { retrieval_ms: 1, synthesis_ms: 2, total_ms: 3 },
};

describe("askAboutMeeting", () => {
  it("sends meeting_id with ask.query", async () => {
    vi.mocked(requestEngineReply).mockResolvedValue(VALID_ASK_REPLY);
    const answer = await askAboutMeeting("m-42", "When is the deadline?");
    expect(requestEngineReply).toHaveBeenCalledWith(
      "ask.query",
      { query: "When is the deadline?", meeting_id: "m-42" },
      120_000,
    );
    expect(answer.headline).toBe("Answer");
    expect(answer.prose[0]?.text).toContain("Friday");
  });

  it("rejects malformed engine payloads", async () => {
    vi.mocked(requestEngineReply).mockResolvedValue({ headline: 1 });
    await expect(askAboutMeeting("m-1", "hi")).rejects.toThrow(/could not read/i);
  });
});
