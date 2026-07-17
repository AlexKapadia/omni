/**
 * Entry point for the desktop meeting-toast window (Vite entry: meeting-toast.html).
 * Content is pushed from the main window — no engine WebSocket here.
 */
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";

import "../styles/tokens.css";
import "../styles/fonts.css";
import "./meeting-toast.css";
import { MEETING_TOAST_CONTENT_EVENT } from "../lib/wire-meeting-toast-desktop";
import {
  applyMeetingToastContent,
  meetingToastContentStore,
} from "./meeting-toast-content-store";
import { MeetingToastView } from "./meeting-toast-view";

function MeetingToastRoot() {
  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        if (cancelled) return;
        unlisten = await listen(MEETING_TOAST_CONTENT_EVENT, (event) => {
          applyMeetingToastContent(meetingToastContentStore, event.payload);
        });
        if (cancelled) {
          unlisten();
        }
      } catch {
        // Web build / tests: no Tauri shell.
      }
    })();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  return <MeetingToastView />;
}

const rootElement = document.getElementById("meeting-toast-root");
if (rootElement === null) {
  throw new Error("Root element #meeting-toast-root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <MeetingToastRoot />
  </StrictMode>,
);
