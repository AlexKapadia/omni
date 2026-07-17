/**
 * Push the configured push-to-talk hotkey to the Tauri shell so the global
 * hold-key binding follows the user's setting.
 *
 * Why this exists: the shell (Rust) registers the DEFAULT key (F9) at startup,
 * because the engine — and therefore the persisted `push_to_talk_hotkey`
 * setting — is not yet reachable when the setup hook runs. This module closes
 * that gap from the UI side (the WebSocket client that CAN read the setting):
 * on boot it fetches the setting and pushes it, and the Hotkey settings card
 * pushes every change, so a user whose default key is taken can rebind it and
 * have it take effect live. The shell stays thin — it never opens the engine's
 * database; the setting always flows through the engine.
 *
 * Fail-safe: every path is non-fatal. Outside the Tauri shell (browser dev,
 * tests) it is a no-op; if the engine read or the command call fails, the shell
 * simply keeps its default F9 binding.
 */
import { invoke } from "@tauri-apps/api/core";
import { getSettings, type SetupRequestFn } from "./setup-settings-repository";

/** True only inside the Tauri shell, where `set_dictation_hotkey` exists. */
function inTauriShell(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Re-register the shell's global hold key to `keys` (the recorded token list). */
export async function pushDictationHotkey(keys: readonly string[]): Promise<void> {
  if (!inTauriShell()) return; // no shell command to call in the browser/tests
  try {
    await invoke("set_dictation_hotkey", { keys });
  } catch {
    // Non-fatal: the shell keeps whatever binding it already holds.
  }
}

/**
 * Read the persisted hotkey from the engine and push it to the shell (boot sync).
 * Retries with the same bounded loop as the setup.status probe — the first
 * attempt often races the still-connecting WebSocket.
 */
export async function syncConfiguredDictationHotkey(
  request?: SetupRequestFn,
  budgetMs: number = 10_000,
): Promise<void> {
  if (!inTauriShell()) return;
  const deadline = Date.now() + budgetMs;
  while (true) {
    try {
      const result = await getSettings(request);
      await pushDictationHotkey(result.settings.pushToTalkHotkey);
      return;
    } catch {
      if (Date.now() >= deadline) {
        // Non-fatal: the default F9 binding stays until Settings is opened/changed.
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 400));
    }
  }
}
