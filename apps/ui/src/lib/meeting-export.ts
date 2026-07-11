/**
 * Download transcript export via meeting.export command.
 */
import { requestEngineReply } from "./meetings-live-repository";

export type MeetingExportFormat = "srt" | "vtt" | "txt" | "pdf" | "docx" | "md";

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
  md: "text/markdown",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

/** Strip Windows-illegal / path-separator chars; fallback ``meeting``. */
export function sanitizeExportFilenameStem(rawTitle: string): string {
  const cleaned = rawTitle
    .replace(/[<>:"/\\|?*\x00-\x1f\x7f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > 0 ? cleaned : "meeting";
}

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
  const stem = sanitizeExportFilenameStem(title);
  return {
    content,
    encoding,
    mime: MIME_BY_FORMAT[format],
    filename: `${stem}.${format}`,
  };
}

export function triggerBrowserDownload(result: MeetingExportResult): void {
  const safeName = sanitizeExportFilenameStem(
    result.filename.replace(/\.[^.]+$/, ""),
  );
  const ext = result.filename.includes(".")
    ? result.filename.slice(result.filename.lastIndexOf("."))
    : "";
  const bytes =
    result.encoding === "base64"
      ? Uint8Array.from(atob(result.content), (ch) => ch.charCodeAt(0))
      : new TextEncoder().encode(result.content);
  const blob = new Blob([bytes], { type: result.mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${safeName}${ext}`;
  anchor.click();
  URL.revokeObjectURL(url);
}
