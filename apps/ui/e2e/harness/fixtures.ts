/**
 * Test fixtures: install the HONEST Tauri shim before every page loads.
 *
 * Plain Chromium has no Tauri runtime, so OS-native calls (the file-open
 * dialog, tray, the pill's window handle) are absent. We stub ONLY those
 * OS-native seams; every data-bearing call (setup.status, ask.query,
 * meetings.*, settings.*, ledger, capture.*) still flows through the REAL
 * engine over the real WebSocket (§4.9.8). What is shimmed:
 *   - window.__omniPickDirectory → returns the real tmp vault path (the seam
 *     pick-vault-directory.ts already exposes for exactly this purpose).
 *   - window.__TAURI_INTERNALS__ → a minimal stub so the pill window (which
 *     imports @tauri-apps/api) renders; invoke/listen resolve to no-ops. The
 *     main shell imports no Tauri and is entirely un-shimmed.
 */
import { test as base, expect } from "@playwright/test";
import { VAULT_DIR } from "./e2e-env";

function installShim(vaultPath: string): void {
  // OS-native folder picker seam: return the real fixture vault path.
  (window as unknown as { __omniPickDirectory: () => string }).__omniPickDirectory = () =>
    vaultPath;
  // Minimal Tauri internals so the pill window (imports @tauri-apps/api) mounts.
  // invoke resolves to null and listen becomes a no-op unlisten — no OS calls.
  (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {
    metadata: {
      currentWindow: { label: "pill" },
      currentWebview: { windowLabel: "pill", label: "pill" },
    },
    invoke: async () => null,
    transformCallback: (cb: unknown) => {
      const id = Math.floor(Math.random() * 1e9);
      (window as unknown as Record<string, unknown>)[`_${id}`] = cb;
      return id;
    },
    convertFileSrc: (p: string) => p,
  };
}

export const test = base.extend({
  // Override the context fixture so the shim is present on EVERY page/frame
  // before any app code runs (addInitScript persists across navigations).
  context: async ({ context }, use) => {
    await context.addInitScript(installShim, VAULT_DIR);
    await use(context);
  },
});

export { expect };
