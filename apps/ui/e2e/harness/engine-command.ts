/**
 * Minimal one-shot engine command over the real WebSocket, for test SETUP only
 * (never the code under test): open a socket, send one command envelope,
 * resolve on the correlated `ok` reply, close. Used by the onboarding spec to
 * flip onboarding_complete on the REAL engine (a valid settings.update key) so
 * the app boots the wizard, then to restore it — no mock, no DB poking.
 *
 * Node 22 provides a global WebSocket, so no dependency is added.
 */
import { ENGINE_WS } from "./e2e-env";

/** Send one command envelope and await its correlated `ok` reply payload. */
export async function sendEngineCommandOnce(
  name: string,
  payload: Record<string, unknown> = {},
  timeoutMs = 15_000,
): Promise<Record<string, unknown>> {
  const id = `test-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const ws = new WebSocket(ENGINE_WS);
  return await new Promise<Record<string, unknown>>((resolve, reject) => {
    const timer = setTimeout(() => {
      ws.close();
      reject(new Error(`engine did not answer ${name} in ${timeoutMs}ms`));
    }, timeoutMs);
    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ v: 1, kind: "command", name, id, payload }));
    });
    ws.addEventListener("error", () => {
      clearTimeout(timer);
      reject(new Error(`engine socket error sending ${name}`));
    });
    ws.addEventListener("message", (event: MessageEvent) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(String(event.data)) as Record<string, unknown>;
      } catch {
        return; // ignore non-JSON frames
      }
      if (msg["kind"] !== "reply" || msg["id"] !== id) return; // not ours
      clearTimeout(timer);
      const replyName = msg["name"];
      const replyPayload = (msg["payload"] ?? {}) as Record<string, unknown>;
      ws.close();
      if (replyName === "ok") resolve(replyPayload);
      else reject(new Error(`engine refused ${name}: ${JSON.stringify(replyPayload)}`));
    });
  });
}

/** Flip the real onboarding_complete setting (test setup/teardown only). */
export async function setOnboardingComplete(complete: boolean): Promise<void> {
  await sendEngineCommandOnce("settings.update", { values: { onboarding_complete: complete } });
}
