/**
 * Entry point for the desktop meeting-toast window (Vite entry: meeting-toast.html).
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../styles/tokens.css";
import "../styles/fonts.css";
import "./meeting-toast.css";
import { startMeetingToastEngineBridge } from "./meeting-toast-engine-bridge";
import { MeetingToastView } from "./meeting-toast-view";

startMeetingToastEngineBridge();

const rootElement = document.getElementById("meeting-toast-root");
if (rootElement === null) {
  throw new Error("Root element #meeting-toast-root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <MeetingToastView />
  </StrictMode>,
);
