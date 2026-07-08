/**
 * Download transcript export via meeting.export command.
 */
import { requestEngineReply } from "./meetings-live-repository";

export async function downloadMeetingExport(
  meetingId: string,
  format: "srt" | "vtt" | "txt",
): Promise<string> {
  const payload = await requestEngineReply(
    "meeting.export",
    { meeting_id: meetingId, format },
    15_000,
  );
  const content = payload["content"];
  if (typeof content !== "string") {
    throw new Error("engine sent a malformed export");
  }
  return content;
}

export function triggerBrowserDownload(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
