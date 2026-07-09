/**
 * Entry point for the captions overlay window (separate Vite entry: captions.html).
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../styles/tokens.css";
import "../styles/fonts.css"; // self-hosted webfonts — this window has its own Vite entry, so it needs its own import
import "./captions.css";
import { startCaptionsEngineBridge } from "./captions-engine-bridge";
import { CaptionsOverlayView } from "./captions-overlay-view";

startCaptionsEngineBridge();

const rootElement = document.getElementById("captions-root");
if (rootElement === null) {
  throw new Error("Root element #captions-root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <CaptionsOverlayView />
  </StrictMode>,
);
