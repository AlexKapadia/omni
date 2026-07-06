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
import { StatusFooter } from "./components/status-footer";
import { tokenDurationSeconds } from "./lib/design-token-motion";
import { startLiveEngineConnection } from "./lib/live-engine-socket";
import { NaomiView } from "./naomi/NaomiView";
import { AskScreen } from "./screens/ask-screen";
import { LibraryScreen } from "./screens/library-screen";
import { LiveMeetingScreen } from "./screens/live-meeting-screen";
import { SettingsScreen } from "./screens/settings-screen";

export default function App() {
  const [activeSection, setActiveSection] = useState<SectionId>("library");
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    // Singleton with an idempotent start — safe under StrictMode double-mount.
    // Deliberately not stopped on unmount: the connection lives as long as the
    // window does, and the footer must stay live across any future remounts.
    startLiveEngineConnection();
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
