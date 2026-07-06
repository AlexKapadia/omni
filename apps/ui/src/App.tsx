/**
 * App shell: left nav rail, main content area, status footer.
 *
 * M0 scope — the three sections are placeholder views over an empty state;
 * real screens replace ViewEmptyState in later milestones. The engine
 * connection is started here so the footer shows live status from first paint.
 */
import { useEffect, useState } from "react";
import { NavRail, type SectionId } from "./components/nav-rail";
import { StatusFooter } from "./components/status-footer";
import { ViewEmptyState } from "./components/view-empty-state";
import { startEngineConnection } from "./lib/engine-connection";

export default function App() {
  const [activeSection, setActiveSection] = useState<SectionId>("meetings");

  useEffect(() => {
    // Singleton with an idempotent start — safe under StrictMode double-mount.
    // Deliberately not stopped on unmount: the connection lives as long as the
    // window does, and the footer must stay live across any future remounts.
    startEngineConnection();
  }, []);

  return (
    <div className="flex h-full flex-col bg-[var(--canvas)] text-[var(--ink)]">
      <div className="flex min-h-0 flex-1">
        <NavRail active={activeSection} onSelect={setActiveSection} />
        <main className="flex min-w-0 flex-1 items-center justify-center overflow-y-auto">
          <ViewEmptyState section={activeSection} />
        </main>
      </div>
      <StatusFooter />
    </div>
  );
}
