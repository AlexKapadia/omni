/**
 * Pure helpers matching a `models.download.completed` file list back to the
 * catalog: which Whisper size finished, or whether the core (Silero+Parakeet)
 * bundle finished. Used to auto-select the model that just became ready.
 */
import {
  WHISPER_MODEL_OPTIONS,
  isCoreSttStatusFile,
  isWhisperStatusFile,
  whisperStatusFile,
  type WhisperModelOption,
} from "./whisper-model-catalog";

/** The Whisper option whose file is in `files`, or null if none matches. */
export function matchCompletedWhisperOption(files: readonly string[]): WhisperModelOption | null {
  const file = files.find(isWhisperStatusFile);
  if (file === undefined) return null;
  return WHISPER_MODEL_OPTIONS.find((o) => whisperStatusFile(o.id) === file) ?? null;
}

/** True when the completed file list includes a core (non-Whisper) model. */
export function coreModelsCompleted(files: readonly string[]): boolean {
  return files.some(isCoreSttStatusFile);
}
