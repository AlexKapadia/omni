/**
 * Fail-closed parser for import.media.progress event payloads.
 */
import { describe, expect, it } from "vitest";
import {
  IMPORT_MEDIA_PROGRESS_EVENT,
  parseImportMediaProgressPayload,
} from "./import-media-progress";

describe("parseImportMediaProgressPayload", () => {
  it("accepts a valid stage + fraction payload", () => {
    expect(parseImportMediaProgressPayload({ stage: "transcribe", fraction: 0.42 })).toEqual({
      stage: "transcribe",
      fraction: 0.42,
      percent: 42,
    });
    expect(IMPORT_MEDIA_PROGRESS_EVENT).toBe("import.media.progress");
  });

  it("rejects malformed payloads fail-closed", () => {
    expect(parseImportMediaProgressPayload(null)).toBeNull();
    expect(parseImportMediaProgressPayload({})).toBeNull();
    expect(parseImportMediaProgressPayload({ stage: "", fraction: 0.5 })).toBeNull();
    expect(parseImportMediaProgressPayload({ stage: "x", fraction: -0.1 })).toBeNull();
    expect(parseImportMediaProgressPayload({ stage: "x", fraction: 1.1 })).toBeNull();
    expect(parseImportMediaProgressPayload({ stage: "x", fraction: "0.5" })).toBeNull();
  });
});
