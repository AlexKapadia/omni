/** Playwright global teardown: stop the real engine and free the pinned port. */
import { stopEngine } from "./engine-process";

export default function globalTeardown(): void {
  console.log("[e2e] stopping engine…");
  stopEngine();
}
