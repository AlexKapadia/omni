/**
 * Sync captions overlay visibility with capture lifecycle and the user's
 * live-captions setting. The overlay window is a separate webview; the main
 * window only invokes the shell show/hide command.
 */
import { invoke } from "@tauri-apps/api/core";

import { transcriptStore } from "./transcript-store";
import type { SettingsStore } from "./settings-store";

function shouldShowOverlay(
  captureStatus: string,
  liveCaptionsOverlay: boolean,
): boolean {
  return liveCaptionsOverlay && captureStatus === "live";
}

async function applyVisibility(visible: boolean): Promise<void> {
  try {
    await invoke("set_captions_overlay_visible", { visible });
  } catch {
    // Non-fatal: overlay is optional chrome; never block the main app.
  }
}

/**
 * Subscribe to capture status and settings; returns an unsubscribe function.
 */
export function wireCaptionsOverlay(settingsStore: SettingsStore): () => void {
  let lastVisible: boolean | null = null;

  const sync = (): void => {
    const captureStatus = transcriptStore.getState().captureStatus;
    const liveCaptionsOverlay =
      settingsStore.getState().settings?.liveCaptionsOverlay ?? true;
    const visible = shouldShowOverlay(captureStatus, liveCaptionsOverlay);
    if (visible === lastVisible) return;
    const wasVisible = lastVisible === true;
    lastVisible = visible;
    if (visible || wasVisible) {
      void applyVisibility(visible);
    }
  };

  const unsubTranscript = transcriptStore.subscribe(sync);
  const unsubSettings = settingsStore.subscribe(sync);
  sync();

  return () => {
    unsubTranscript();
    unsubSettings();
    if (lastVisible === true) {
      void applyVisibility(false);
    }
  };
}
