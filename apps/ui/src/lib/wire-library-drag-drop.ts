/**
 * Wire Tauri native file drag-and-drop on the Library screen to media import.
 */
import { importMediaFile } from "./meetings-live-repository";

const MEDIA_EXTENSIONS = new Set([
  ".wav",
  ".mp3",
  ".m4a",
  ".flac",
  ".ogg",
  ".webm",
  ".mp4",
  ".mkv",
  ".mov",
]);

function isMediaPath(path: string): boolean {
  const lower = path.toLowerCase();
  const dot = lower.lastIndexOf(".");
  if (dot < 0) return false;
  return MEDIA_EXTENSIONS.has(lower.slice(dot));
}

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function wireLibraryDragDrop(onImported: () => void): () => void {
  if (!isTauriRuntime()) {
    return () => undefined;
  }
  let disposed = false;
  let unlisten: (() => void) | undefined;
  void (async () => {
    const { getCurrentWebview } = await import("@tauri-apps/api/webview");
    if (disposed) return;
    unlisten = await getCurrentWebview().onDragDropEvent((event) => {
      if (event.payload.type !== "drop") return;
      const paths = event.payload.paths.filter(isMediaPath);
      if (paths.length === 0) return;
      void (async () => {
        for (const path of paths) {
          try {
            await importMediaFile(path);
          } catch {
            // Import errors surface via meetings store refresh; keep going.
          }
        }
        onImported();
      })();
    });
  })();
  return () => {
    disposed = true;
    unlisten?.();
  };
}
