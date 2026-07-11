/**
 * Pure copy for the Home "privacy" help tile — never claims complete offline
 * when cloud STT or cloud summary is configured.
 */
import type { EngineSettings } from "../lib/setup-settings-payloads";

export interface LocalPrivacyCopy {
  readonly title: string;
  readonly body: string;
}

const LOCAL_STT = new Set(["parakeet", "whisper"]);
const LOCAL_SUMMARY = new Set(["ollama", "builtin-ai"]);

export function isFullyLocalAi(settings: EngineSettings | null): boolean {
  if (settings === null) return false;
  return (
    LOCAL_STT.has(settings.sttEngine) && LOCAL_SUMMARY.has(settings.summaryProvider)
  );
}

export function localPrivacyCopy(settings: EngineSettings | null): LocalPrivacyCopy {
  if (isFullyLocalAi(settings)) {
    return {
      title: "Local-first privacy",
      body: "Capture, transcription, and vault stay on this device with your current local AI settings.",
    };
  }
  return {
    title: "Local-first with optional cloud AI",
    body: "Local-first: capture and vault stay on this device. Cloud AI only when you configure it.",
  };
}
