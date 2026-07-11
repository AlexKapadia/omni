/**
 * Non-Tauri fallback must not return a ~/ relative path the engine rejects.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { pickVaultDirectory } from "./pick-vault-directory";

afterEach(() => {
  delete (window as unknown as { __omniPickDirectory?: unknown }).__omniPickDirectory;
  delete (window as unknown as { __TAURI__?: unknown }).__TAURI__;
  vi.restoreAllMocks();
});

describe("pickVaultDirectory", () => {
  it("returns null in a plain browser (no Tauri) instead of a ~/ path", async () => {
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("~/Documents/Omni Steroid");
    const path = await pickVaultDirectory();
    expect(path).toBeNull();
    expect(prompt).not.toHaveBeenCalled();
  });

  it("still honours the __omniPickDirectory test hook", async () => {
    (window as unknown as { __omniPickDirectory: () => string }).__omniPickDirectory = () =>
      "C:/Users/test/Vault";
    await expect(pickVaultDirectory()).resolves.toBe("C:/Users/test/Vault");
  });
});
