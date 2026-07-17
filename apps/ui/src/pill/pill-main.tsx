/**
 * Entry point for the pill window (separate Vite entry: /pill.html).
 * Mounts the pill view and starts the Tauri/engine bridge; nothing else.
 */
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import "../styles/tokens.css";
import "../styles/fonts.css"; // self-hosted webfonts — this window has its own Vite entry, so it needs its own import
import "./pill.css";
import { fetchPillSettings, startDictationPillBridge } from "./dictation-engine-bridge";
import { dictationPillStore } from "./dictation-pill-store";
import { DictationPillView } from "./dictation-pill-view";
import { formatHoldLabel } from "./format-hold-label";

startDictationPillBridge(dictationPillStore);

function PillRoot() {
  const [holdLabel, setHoldLabel] = useState("Hold F9");
  useEffect(() => {
    // Fetch over the pill's own socket (main-window getSettings always rejects here).
    void fetchPillSettings()
      .then((result) => setHoldLabel(formatHoldLabel(result.settings.pushToTalkHotkey)))
      .catch(() => {
        // Non-fatal: keep the default F9 hint until settings are reachable.
      });
  }, []);
  return <DictationPillView holdLabel={holdLabel} />;
}

const rootElement = document.getElementById("pill-root");
if (rootElement === null) {
  // Fail loudly: a missing mount point means pill.html drifted from this file.
  throw new Error("Root element #pill-root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <PillRoot />
  </StrictMode>,
);
