/**
 * Wire Tauri native file drag-and-drop on the Library screen to media import.
 */
import { importMediaFile } from "./meetings-live-repository";

const MEDIA_EXTENSIONS = new Set([
  ".wav",
  ".mp3",
  ".m4a",
  ".aac",
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

function resolveIdentifySpeakers(
  value: boolean | (() => boolean) | undefined,
): boolean {
  if (typeof value === "function") return value() === true;
  return value === true;
}

export type LibraryDragDropOptions = {
  /** Same toggle as the Import media button — read at drop time. */
  readonly identifySpeakers?: boolean | (() => boolean);
  /** Surface per-file import failures (silent swallow was a bug). */
  readonly onError?: (message: string) => void;
};

export function wireLibraryDragDrop(
  onImported: () => void,
  options: LibraryDragDropOptions = {},
): () => void {
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
        let imported = 0;
        for (const path of paths) {
          try {
            await importMediaFile(path, undefined, {
              identifySpeakers: resolveIdentifySpeakers(options.identifySpeakers),
            });
            imported += 1;
          } catch (err) {
            const message =
              err instanceof Error ? err.message : `Could not import ${path}`;
            options.onError?.(message);
          }
        }
        if (imported > 0) onImported();
      })();
    });
  })();
  return () => {
    disposed = true;
    unlisten?.();
  };
}
