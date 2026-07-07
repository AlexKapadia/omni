/**
 * Folder picker for the onboarding vault step, via the Tauri dialog plugin
 * (@tauri-apps/plugin-dialog `open({ directory: true })`).
 *
 * A window-level test seam (`__omniPickDirectory`) wins when present so the
 * live E2E suite can drive the picker against the running vite app WITHOUT a
 * Tauri runtime — the real plugin call only happens inside the desktop shell.
 * The plugin is imported dynamically so a plain browser never evaluates its
 * IPC module at load time.
 */

/** Optional test/E2E hook injected on window (returns the chosen path or null). */
interface PickerHook {
  __omniPickDirectory?: () => Promise<string | null> | string | null;
}

export async function pickVaultDirectory(): Promise<string | null> {
  const hook = (window as unknown as PickerHook).__omniPickDirectory;
  if (typeof hook === "function") {
    return hook() ?? null;
  }
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({ directory: true, multiple: false, title: "Choose your vault folder" });
  // The plugin returns a string for a single directory, or null if cancelled.
  return typeof selected === "string" ? selected : null;
}
