/**
 * startModelsDownload accepts optional Whisper bundle args.
 */
import { describe, expect, it, vi } from "vitest";

import { startModelsDownload } from "./setup-settings-repository";

describe("startModelsDownload", () => {
  it("sends empty payload for the core Silero+Parakeet bundle", async () => {
    const request = vi.fn().mockResolvedValue({});
    await startModelsDownload(request);
    expect(request).toHaveBeenCalledWith("models.download", {}, expect.any(Number));
  });

  it("sends bundle=whisper and model_id for a Whisper size", async () => {
    const request = vi.fn().mockResolvedValue({});
    await startModelsDownload(request, { bundle: "whisper", modelId: "small" });
    expect(request).toHaveBeenCalledWith(
      "models.download",
      { bundle: "whisper", model_id: "small" },
      expect.any(Number),
    );
  });
});
