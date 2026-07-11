/**
 * Onboarding engine + summary selection must persist the chosen STT engine
 * and derive summaryProvider from the model id (not hardcode Parakeet).
 */
import { describe, expect, it, vi } from "vitest";
import { saveEngineSelection } from "./onboarding-flow-actions";

describe("saveEngineSelection", () => {
  it("persists whisper + default whisper model id and gemini provider", async () => {
    const update = vi.fn(async () => ({}));
    await saveEngineSelection("whisper", "gemini-2.5-flash", update);
    expect(update).toHaveBeenCalledWith(
      {
        stt_engine: "whisper",
        stt_model_id: "large-v3-turbo",
        summary_model_id: "gemini-2.5-flash",
        summary_provider: "gemini",
      },
      null,
    );
  });

  it("persists parakeet with empty model id and anthropic for claude models", async () => {
    const update = vi.fn(async () => ({}));
    await saveEngineSelection("parakeet", "claude-sonnet-4-5", update);
    expect(update).toHaveBeenCalledWith(
      {
        stt_engine: "parakeet",
        stt_model_id: "",
        summary_model_id: "claude-sonnet-4-5",
        summary_provider: "anthropic",
      },
      null,
    );
  });
});
