import { describe, expect, it, vi } from "vitest";
import { downloadMeetingExport, sanitizeExportFilenameStem } from "./meeting-export";

vi.mock("./meetings-live-repository", () => ({
  requestEngineReply: vi.fn(),
}));

import { requestEngineReply } from "./meetings-live-repository";

describe("sanitizeExportFilenameStem", () => {
  it("strips illegal path characters and collapses whitespace", () => {
    expect(sanitizeExportFilenameStem('Q3: "Plan"/A|B?*')).toBe("Q3 Plan A B");
    expect(sanitizeExportFilenameStem("a\\b/c")).toBe("a b c");
    expect(sanitizeExportFilenameStem("   ")).toBe("meeting");
    expect(sanitizeExportFilenameStem("")).toBe("meeting");
  });
});

describe("downloadMeetingExport md", () => {
  it("requests md format and returns text content", async () => {
    vi.mocked(requestEngineReply).mockResolvedValue({
      content: "# Meeting\n\n## Transcript\n",
      encoding: "text",
    });
    const result = await downloadMeetingExport("m-1", "md", "Standup");
    expect(requestEngineReply).toHaveBeenCalledWith(
      "meeting.export",
      { meeting_id: "m-1", format: "md" },
      30_000,
    );
    expect(result.mime).toBe("text/markdown");
    expect(result.filename).toBe("Standup.md");
    expect(result.content).toContain("# Meeting");
  });

  it("sanitizes unsafe titles in the download filename", async () => {
    vi.mocked(requestEngineReply).mockResolvedValue({
      content: "body",
      encoding: "text",
    });
    const result = await downloadMeetingExport("m-2", "txt", 'Evil<>:"/\\|?* name');
    expect(result.filename).toBe("Evil name.txt");
  });
});
