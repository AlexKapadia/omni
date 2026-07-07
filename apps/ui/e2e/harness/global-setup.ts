/**
 * Playwright global setup: bring up the REAL stack once for the whole suite.
 * DB → migrate + index + seed → engine sidecar → health 200 → REAL ask.query
 * gate. Nothing is mocked; if the real path is not green this throws and the
 * whole run stops (we never test/record against a broken product).
 */
import { bootEngine } from "./engine-process";

export default async function globalSetup(): Promise<void> {
  console.log("[e2e] booting REAL engine + seeding real data (no mock mode)…");
  await bootEngine();
  console.log("[e2e] engine healthy and answering real ask.query ✓");
}
