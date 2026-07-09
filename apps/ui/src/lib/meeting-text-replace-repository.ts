import { requestEngineReply } from "./meetings-live-repository";

export type TextReplaceTarget = "transcript" | "enhanced_notes" | "both";

export interface TextReplaceResult {
  readonly transcriptSegments: number;
  readonly enhancedNotes: number;
}

export async function replaceMeetingText(
  meetingId: string,
  find: string,
  replace: string,
  target: TextReplaceTarget,
): Promise<TextReplaceResult> {
  const payload = await requestEngineReply(
    "meeting.text.replace",
    { meeting_id: meetingId, find, replace, target },
    30_000,
  );
  const segments = payload["transcript_segments"];
  const notes = payload["enhanced_notes"];
  return {
    transcriptSegments: typeof segments === "number" ? segments : 0,
    enhancedNotes: typeof notes === "number" ? notes : 0,
  };
}
