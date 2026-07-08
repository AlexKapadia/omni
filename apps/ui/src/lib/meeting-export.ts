/**
 * Download transcript export via meeting.export command.
 */
import { requestEngineReply } from "./meetings-live-repository";

export type MeetingExportFormat = "srt" | "vtt" | "txt" | "pdf" | "docx";

export interface MeetingExportResult {
  readonly content: string;
  readonly encoding: "text" | "base64";
  readonly mime: string;
  readonly filename: string;
}

const MIME_BY_FORMAT: Record<MeetingExportFormat, string> = {
  srt: "text/plain",
  vtt: "text/vtt",
  txt: "text/plain",
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

export async function downloadMeetingExport(
  meetingId: string,
  format: MeetingExportFormat,
  title = "meeting",
): Promise<MeetingExportResult> {
  const payload = await requestEngineReply(
    "meeting.export",
    { meeting_id: meetingId, format },
    30_000,
  );
  const content = payload["content"];
  if (typeof content !== "string") {
    throw new Error("engine sent a malformed export");
  }
  const encoding = payload["encoding"] === "base64" ? "base64" : "text";
  return {
    content,
    encoding,
    mime: MIME_BY_FORMAT[format],
    filename: `${title}.${format}`,
  };
}

export function triggerBrowserDownload(result: MeetingExportResult): void {
  const bytes =
    result.encoding === "base64"
      ? Uint8Array.from(atob(result.content), (ch) => ch.charCodeAt(0))
      : new TextEncoder().encode(result.content);
  const blob = new Blob([bytes], { type: result.mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = result.filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
