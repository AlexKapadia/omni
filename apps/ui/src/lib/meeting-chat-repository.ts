/**
 * Library meeting Chat — Ask scoped to one meeting_id.
 *
 * Uses the same ask.answer correlator as the Ask screen (createEngineAskTransport),
 * not the meetings ok-only requestEngineReply path.
 */
import {
  ASK_QUERY_COMMAND_NAME,
  parseAskAnswerPayload,
  type AskQueryTransport,
} from "./engine-ask-answer-provider";
import type { AskAnswer } from "./ask-store";
import { createEngineAskTransport } from "./engine-ask-transport";

export async function askAboutMeeting(
  meetingId: string,
  query: string,
  transport: AskQueryTransport = createEngineAskTransport(),
): Promise<AskAnswer> {
  const payload = await transport.request(ASK_QUERY_COMMAND_NAME, {
    query,
    meeting_id: meetingId,
  });
  const parsed = parseAskAnswerPayload(payload);
  if (parsed === null) {
    throw new Error("The engine returned an answer the app could not read.");
  }
  return parsed;
}
