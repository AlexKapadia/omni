import { describe, expect, it, vi } from "vitest";
import { replaceMeetingText } from "./meeting-text-replace-repository";

vi.mock("./meetings-live-repository", () => ({
  requestEngineReply: vi.fn(),
}));

import { requestEngineReply } from "./meetings-live-repository";

describe("replaceMeetingText", () => {
  it("maps engine reply fields to camelCase", async () => {
    vi.mocked(requestEngineReply).mockResolvedValue({
      transcript_segments: 2,
      enhanced_notes: 1,
    });
    const result = await replaceMeetingText("m-1", "foo", "bar", "both");
    expect(result).toEqual({ transcriptSegments: 2, enhancedNotes: 1 });
    expect(requestEngineReply).toHaveBeenCalledWith(
      "meeting.text.replace",
      { meeting_id: "m-1", find: "foo", replace: "bar", target: "both" },
      30_000,
    );
  });

  it("defaults missing counts to zero", async () => {
    vi.mocked(requestEngineReply).mockResolvedValue({});
    const result = await replaceMeetingText("m-1", "a", "b", "transcript");
    expect(result).toEqual({ transcriptSegments: 0, enhancedNotes: 0 });
  });
});
