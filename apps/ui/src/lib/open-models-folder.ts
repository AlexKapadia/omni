/**
 * Opens the on-device models folder: asks the engine for the real path, then
 * reveals it in the OS file explorer via the Tauri shell command. If that
 * fails (web build, missing Rust command, sandboxed environment) falls back
 * to copying the path and toasting instead — never a silent no-op.
 */
import { invoke } from "@tauri-apps/api/core";
import { openModelsFolder } from "./setup-settings-repository";
import { copyTextToClipboard } from "./copy-to-clipboard";
import { showToast } from "./toast-store";

export async function openModelsFolderAndReveal(
  fetchPath: () => Promise<string> = openModelsFolder,
  reveal: (path: string) => Promise<void> = (path) =>
    invoke("reveal_path_in_explorer", { path }).then(() => undefined),
): Promise<void> {
  const path = await fetchPath();
  try {
    await reveal(path);
    showToast("Opened the models folder.", "success");
  } catch {
    await copyTextToClipboard(path);
    showToast(`Models folder path copied: ${path}`, "info");
  }
}
