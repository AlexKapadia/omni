import { parseAskAnswerPayload, type AskAnswer } from "./engine-ask-answer-provider";
import { requestEngineReply } from "./meetings-live-repository";

export async function askAboutMeeting(meetingId: string, query: string): Promise<AskAnswer> {
  const payload = await requestEngineReply(
    "ask.query",
    { query, meeting_id: meetingId },
    120_000,
  );
  const parsed = parseAskAnswerPayload(payload);
  if (parsed === null) {
    throw new Error("The engine returned an answer the app could not read.");
  }
  return parsed;
}
