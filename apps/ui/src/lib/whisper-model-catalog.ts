/**
 * Meetily-compatible Whisper ggml catalog (ggerganov/whisper.cpp).
 * Basic models show by default; the rest live under Advanced.
 */
export interface WhisperModelOption {
  readonly id: string;
  readonly filename: string;
  readonly label: string;
  readonly detail: string;
  readonly sizeMb: number;
  readonly basic: boolean;
}

export const WHISPER_MODEL_OPTIONS: readonly WhisperModelOption[] = [
  { id: "small", filename: "ggml-small.bin", label: "Small", detail: "Good accuracy · Medium speed", sizeMb: 466, basic: true },
  { id: "medium-q5_0", filename: "ggml-medium-q5_0.bin", label: "Medium", detail: "Professional · Quantized", sizeMb: 514, basic: true },
  { id: "large-v3-q5_0", filename: "ggml-large-v3-q5_0.bin", label: "Large V3 Compressed", detail: "High accuracy · Quantized", sizeMb: 1031, basic: true },
  { id: "large-v3-turbo", filename: "ggml-large-v3-turbo.bin", label: "Large V3 Turbo", detail: "Best accuracy with speed", sizeMb: 1549, basic: true },
  { id: "large-v3", filename: "ggml-large-v3.bin", label: "Large V3", detail: "Most accurate", sizeMb: 2951, basic: true },
  { id: "tiny", filename: "ggml-tiny.bin", label: "Tiny", detail: "Fastest · Real-time", sizeMb: 74, basic: false },
  { id: "base", filename: "ggml-base.bin", label: "Base", detail: "Fast · Balanced", sizeMb: 142, basic: false },
  { id: "medium", filename: "ggml-medium.bin", label: "Medium (full)", detail: "High accuracy · Slow", sizeMb: 1463, basic: false },
  { id: "tiny-q5_1", filename: "ggml-tiny-q5_1.bin", label: "Tiny Q5", detail: "Quantized tiny", sizeMb: 31, basic: false },
  { id: "base-q5_1", filename: "ggml-base-q5_1.bin", label: "Base Q5", detail: "Quantized base", sizeMb: 57, basic: false },
  { id: "small-q5_1", filename: "ggml-small-q5_1.bin", label: "Small Q5", detail: "Quantized small", sizeMb: 181, basic: false },
  { id: "large-v3-turbo-q5_0", filename: "ggml-large-v3-turbo-q5_0.bin", label: "Large Turbo Q5", detail: "Quantized turbo", sizeMb: 547, basic: false },
];

export const DEFAULT_WHISPER_MODEL_ID = "large-v3-turbo";

export function whisperStatusFile(modelId: string): string {
  const hit = WHISPER_MODEL_OPTIONS.find((o) => o.id === modelId);
  return hit?.filename ?? `ggml-${modelId}.bin`;
}

export function isWhisperStatusFile(file: string): boolean {
  return file.startsWith("ggml-") && file.endsWith(".bin");
}

export function isCoreSttStatusFile(file: string): boolean {
  return !isWhisperStatusFile(file);
}

export function formatWhisperSize(sizeMb: number): string {
  return sizeMb >= 1000 ? `${(sizeMb / 1000).toFixed(1)} GB` : `${sizeMb} MB`;
}
