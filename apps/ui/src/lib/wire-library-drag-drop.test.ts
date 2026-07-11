/**
 * Drag-drop import must honor identifySpeakers and surface failures.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const importMediaFile = vi.fn();
vi.mock("./meetings-live-repository", () => ({
  importMediaFile: (...args: unknown[]) => importMediaFile(...args),
}));

type DropHandler = (event: {
  payload: { type: string; paths: string[] };
}) => void;

let dropHandler: DropHandler | undefined;
const unlisten = vi.fn();

vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({
    onDragDropEvent: async (handler: DropHandler) => {
      dropHandler = handler;
      return unlisten;
    },
  }),
}));

import { wireLibraryDragDrop } from "./wire-library-drag-drop";

describe("wireLibraryDragDrop", () => {
  beforeEach(() => {
    dropHandler = undefined;
    importMediaFile.mockReset();
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      value: {},
      configurable: true,
      writable: true,
    });
  });

  it("passes identifySpeakers into importMediaFile and reports errors", async () => {
    importMediaFile.mockResolvedValueOnce("m-ok").mockRejectedValueOnce(new Error("bad file"));

    const onImported = vi.fn();
    const onError = vi.fn();
    const dispose = wireLibraryDragDrop(onImported, {
      identifySpeakers: () => true,
      onError,
    });

    await vi.waitFor(() => {
      expect(dropHandler).toBeDefined();
    });

    dropHandler!({
      payload: { type: "drop", paths: ["C:/a.mp3", "C:/b.wav", "C:/readme.txt"] },
    });

    await vi.waitFor(() => {
      expect(importMediaFile).toHaveBeenCalledTimes(2);
    });

    expect(importMediaFile).toHaveBeenNthCalledWith(1, "C:/a.mp3", undefined, {
      identifySpeakers: true,
    });
    expect(importMediaFile).toHaveBeenNthCalledWith(2, "C:/b.wav", undefined, {
      identifySpeakers: true,
    });
    expect(onError).toHaveBeenCalledWith("bad file");
    expect(onImported).toHaveBeenCalledTimes(1);
    dispose();
  });

  it("accepts .aac paths as media (picker already lists aac)", async () => {
    importMediaFile.mockResolvedValueOnce("m-aac");
    const onImported = vi.fn();
    wireLibraryDragDrop(onImported);
    await vi.waitFor(() => {
      expect(dropHandler).toBeDefined();
    });
    dropHandler!({
      payload: { type: "drop", paths: ["C:/clip.aac", "C:/notes.txt"] },
    });
    await vi.waitFor(() => {
      expect(importMediaFile).toHaveBeenCalledTimes(1);
    });
    expect(importMediaFile).toHaveBeenCalledWith("C:/clip.aac", undefined, {
      identifySpeakers: false,
    });
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("is a no-op outside Tauri", () => {
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    const dispose = wireLibraryDragDrop(vi.fn());
    expect(dropHandler).toBeUndefined();
    dispose();
  });
});
