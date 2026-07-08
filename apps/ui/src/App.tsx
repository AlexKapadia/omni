/**
 * App shell: left nav rail, the active screen, status footer.
 *
 * State-based routing (no router dep): NavRail drives which screen renders,
 * with the 300ms view-transition motion from the design tokens. The single
 * engine connection (status heartbeats + capture/transcript events over one
 * socket) is started here so every screen sees live state from first paint.
 */
import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { NavRail, type SectionId } from "./components/nav-rail";
import { OmniMark } from "./components/omni-mark";
import { StatusFooter } from "./components/status-footer";
import { tokenDurationSeconds } from "./lib/design-token-motion";
import { startLiveEngineConnection } from "./lib/live-engine-socket";
import { wireTrayStartCapture } from "./lib/wire-tray-capture";
import { wireCaptionsOverlay } from "./lib/wire-captions-overlay";
import { loadSettings } from "./lib/settings-actions";
import { appSettingsStore } from "./screens/settings-screen";
import { getSetupStatus } from "./lib/setup-settings-repository";
import { syncConfiguredDictationHotkey } from "./lib/sync-dictation-hotkey";
import type { SetupStatus } from "./lib/setup-settings-payloads";
import { NaomiView } from "./naomi/NaomiView";
import { OnboardingWizard } from "./screens/onboarding/onboarding-wizard";
import { AskScreen } from "./screens/ask-screen";
import { LibraryScreen } from "./screens/library-screen";
import { LiveMeetingScreen } from "./screens/live-meeting-screen";
import { SettingsScreen } from "./screens/settings-screen";

/** Boot gate: first-run onboarding vs the main shell, from real setup.status. */
type Gate = "checking" | "onboarding" | "app";

/**
 * App root. On boot it starts the single engine connection and asks the engine
 * for the real setup.status: an incomplete setup renders the first-run wizard;
 * otherwise the main shell. If the check cannot be reached the shell still
 * loads (engine issues surface in the footer) — we never force a returning user
 * back through onboarding on a transient error.
 */
export default function App({
  checkStatus = getSetupStatus,
  bootRetryBudgetMs = 10_000,
}: {
  readonly checkStatus?: () => Promise<SetupStatus>;
  // Bounded retry window for the cold-boot setup.status probe. Injectable so
  // tests can assert the give-up-and-show-shell path without a real 10 s wait.
  readonly bootRetryBudgetMs?: number;
} = {}) {
  const [gate, setGate] = useState<Gate>("checking");

  useEffect(() => {
    startLiveEngineConnection(); // idempotent; safe under StrictMode double-mount
    let unlistenTray: (() => void) | undefined;
    void (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlistenTray = await wireTrayStartCapture((event, handler) =>
          listen(event, handler).then((fn) => fn),
        );
      } catch {
        // Web build / tests: no Tauri shell — tray capture is unavailable.
      }
    })();
    // Apply the user's configured push-to-talk key to the shell's global hold
    // binding (the shell boots on the default F9 until this lands). No-op
    // outside the Tauri shell; non-fatal if the engine is not up yet.
    void syncConfiguredDictationHotkey();
    let cancelled = false;
    // The engine WebSocket takes a beat to open on a cold boot, so the very
    // first setup.status can fail simply because the socket is not open yet.
    // Falling straight to "app" on that transient failure would (a) skip a
    // first-run user past onboarding and (b) render the shell before its data
    // can load. So we retry on a short cadence while the socket comes up, and
    // only commit to "app" once the engine is genuinely unreachable past a
    // bounded deadline (a returning user is never trapped on the loader).
    const deadline = Date.now() + bootRetryBudgetMs;
    const attempt = (): void => {
      void checkStatus()
        .then((status) => {
          if (cancelled) return;
          setGate(status.onboardingComplete && status.setupComplete ? "app" : "onboarding");
        })
        .catch(() => {
          if (cancelled) return;
          if (Date.now() < deadline) {
            window.setTimeout(attempt, 400); // socket still opening — try again
          } else {
            setGate("app"); // engine truly unreachable: don't trap the user
          }
        });
    };
    attempt();
    return () => {
      cancelled = true;
      unlistenTray?.();
    };
  }, [checkStatus, bootRetryBudgetMs]);

  if (gate === "checking") {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--canvas)]" aria-label="Starting Omni">
        <span className="omni-breathe" aria-hidden>
          <OmniMark size={64} />
        </span>
      </div>
    );
  }
  if (gate === "onboarding") {
    return <OnboardingWizard onComplete={() => setGate("app")} />;
  }
  return <MainShell />;
}

function MainShell() {
  const [activeSection, setActiveSection] = useState<SectionId>("library");
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    void loadSettings(appSettingsStore);
    let unwireCaptions: (() => void) | undefined;
    try {
      unwireCaptions = wireCaptionsOverlay(appSettingsStore);
    } catch {
      // Web build / tests: no Tauri shell.
    }
    return () => unwireCaptions?.();
  }, []);

  return (
    <div className="flex h-full flex-col bg-[var(--canvas)] text-[var(--ink)]">
      <div className="flex min-h-0 flex-1">
        <NavRail active={activeSection} onSelect={setActiveSection} />
        <main className="relative min-w-0 flex-1 overflow-hidden">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={activeSection}
              className="h-full"
              // View transition: 300ms ease-out, transform/opacity only.
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{
                type: "tween",
                ease: [0, 0, 0.2, 1],
                duration: reducedMotion ? 0 : tokenDurationSeconds("--dur-page"),
              }}
            >
              {activeSection === "library" && (
                <LibraryScreen onStartCapture={() => setActiveSection("live")} />
              )}
              {activeSection === "live" && <LiveMeetingScreen />}
              {activeSection === "ask" && <AskScreen />}
              {activeSection === "naomi" && <NaomiView />}
              {activeSection === "settings" && <SettingsScreen />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <StatusFooter />
    </div>
  );
}
