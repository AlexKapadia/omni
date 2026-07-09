import { requestSetupCommand } from "./setup-settings-transport";

export const SPEAKER_ENROLL_COMMAND = "speaker.enroll";

export async function enrollSpeaker(
  displayName: string,
  audioWavBase64?: string,
): Promise<{ readonly voiceEnrolled: boolean }> {
  const payload: Record<string, unknown> = { display_name: displayName };
  if (audioWavBase64 !== undefined) {
    payload["audio_wav_base64"] = audioWavBase64;
  }
  const reply = await requestSetupCommand(SPEAKER_ENROLL_COMMAND, payload);
  const voiceEnrolled = reply["voice_enrolled"];
  return { voiceEnrolled: voiceEnrolled === true };
}
