/**
 * Bridge inject leg: an inbound inject final triggers the shell paste with
 * the CLEANED text, and the outcome (success, honest failure, thrown
 * invoke) lands in the store as an injection-result. Note finals must
 * never trigger a paste. The hold-pressed payload parser is fail-closed:
 * malformed shell payloads collapse to the safe note path.
 */
import { describe, expect, it } from "vitest";

import {
  createDictationEventDispatcher,
  parseHoldPressedPayload,
  resolveInjectRequested,
} from "./dictation-engine-bridge";
import { createDictationPillStore, dispatchPillEvent } from "./dictation-pill-store";

function eventFrame(name: string, payload: Record<string, unknown>): string {
  return JSON.stringify({ v: 1, kind: "event", name, id: "t-1", payload });
}

const INJECT_FINAL_PAYLOAD = {
  mode: "inject",
  text: "um send the report",
  cleaned_text: "Send the report.",
  cleanup_source: "model",
  cleanup_latency_ms: 400,
};

function storeAwaitingFinal() {
  const store = createDictationPillStore();
  dispatchPillEvent(store, { type: "hold-pressed", atMs: 0, injectEligible: true });
  dispatchPillEvent(store, { type: "hold-released" });
  return store;
}

async function flushMicrotasks(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("inject final -> shell paste", () => {
  it("pastes the CLEANED text and records the real outcome", async () => {
    const store = storeAwaitingFinal();
    const calls: Array<{ text: string; hwnd: number }> = [];
    const dispatch = createDictationEventDispatcher(store, async (text, hwnd) => {
      calls.push({ text, hwnd });
      return { ok: true, elapsed_ms: 361, failure_reason: null };
    });

    dispatch(eventFrame("dictation.final", INJECT_FINAL_PAYLOAD));
    await flushMicrotasks();

    expect(calls).toHaveLength(1);
    expect(calls[0]?.text).toBe("Send the report."); // cleaned, not raw
    const state = store.getState();
    expect(state).toMatchObject({
      phase: "result",
      injection: { status: "done", elapsedMs: 361 },
    });
  });

  it("a shell-reported failure lands with its honest reason", async () => {
    const store = storeAwaitingFinal();
    const dispatch = createDictationEventDispatcher(store, async () => ({
      ok: false,
      elapsed_ms: 12,
      failure_reason: "target app runs elevated (admin); text left on the clipboard",
    }));

    dispatch(eventFrame("dictation.final", INJECT_FINAL_PAYLOAD));
    await flushMicrotasks();

    expect(store.getState()).toMatchObject({
      injection: {
        status: "failed",
        reason: "target app runs elevated (admin); text left on the clipboard",
      },
    });
  });

  it("a THROWN invoke still surfaces as an honest failure, never a hang", async () => {
    const store = storeAwaitingFinal();
    const dispatch = createDictationEventDispatcher(store, async () => {
      throw new Error("ipc torn");
    });

    dispatch(eventFrame("dictation.final", INJECT_FINAL_PAYLOAD));
    await flushMicrotasks();

    const state = store.getState();
    expect(state.phase).toBe("result");
    expect(state).toMatchObject({ injection: { status: "failed" } });
  });

  it("falls back to the RAW text when cleaned_text is absent", async () => {
    const store = storeAwaitingFinal();
    const calls: string[] = [];
    const dispatch = createDictationEventDispatcher(store, async (text) => {
      calls.push(text);
      return { ok: true, elapsed_ms: 5, failure_reason: null };
    });

    dispatch(
      eventFrame("dictation.final", { mode: "inject", text: "raw words land" }),
    );
    await flushMicrotasks();
    expect(calls).toEqual(["raw words land"]); // never fail the user's words
  });

  it("note and command finals never trigger a paste", async () => {
    for (const payload of [
      { mode: "note", text: "buy milk" },
      {
        mode: "command",
        text: "Omni, schedule lunch",
        intent: { intent_type: "create_event", fields: {}, confidence: 0.9 },
      },
    ]) {
      const store = storeAwaitingFinal();
      let pasteCalls = 0;
      const dispatch = createDictationEventDispatcher(store, async () => {
        pasteCalls += 1;
        return { ok: true, elapsed_ms: 1, failure_reason: null };
      });
      dispatch(eventFrame("dictation.final", payload));
      await flushMicrotasks();
      expect(pasteCalls).toBe(0);
      expect(store.getState().phase).toBe("result");
    }
  });

  it("a malformed final frame touches nothing (fail closed)", async () => {
    const store = storeAwaitingFinal();
    let pasteCalls = 0;
    const dispatch = createDictationEventDispatcher(store, async () => {
      pasteCalls += 1;
      return { ok: true, elapsed_ms: 1, failure_reason: null };
    });
    dispatch(eventFrame("dictation.final", { mode: "inject" })); // text missing
    await flushMicrotasks();
    expect(pasteCalls).toBe(0);
    expect(store.getState().phase).toBe("processing"); // still waiting honestly
  });
});

describe("resolveInjectRequested", () => {
  it("arms inject while listening before hold-released", () => {
    expect(
      resolveInjectRequested({
        phase: "listening",
        startedAtMs: 0,
        liveText: "",
        commandDetected: false,
        injectArmed: true,
      }),
    ).toBe(true);
  });

  it("keeps inject armed through processing after hold-released", () => {
    expect(
      resolveInjectRequested({
        phase: "processing",
        startedAtMs: 0,
        liveText: "hello",
        commandDetected: false,
        injectArmed: true,
      }),
    ).toBe(true);
  });

  it("denies inject when command mode is detected", () => {
    expect(
      resolveInjectRequested({
        phase: "listening",
        startedAtMs: 0,
        liveText: "Omni schedule lunch",
        commandDetected: true,
        injectArmed: true,
      }),
    ).toBe(false);
  });
});

describe("hold-pressed payload parsing (fail closed to note mode)", () => {
  it("accepts the pinned shell shape", () => {
    expect(
      parseHoldPressedPayload({ inject_eligible: true, target_hwnd: 132464 }),
    ).toEqual({ inject_eligible: true, target_hwnd: 132464 });
  });

  it.each([
    [undefined],
    [null],
    ["string"],
    [{}],
    [{ inject_eligible: "yes", target_hwnd: 1 }],
    [{ inject_eligible: true, target_hwnd: "1" }],
    [{ inject_eligible: true, target_hwnd: Number.NaN }],
  ])("%j collapses to the safe note path", (payload) => {
    expect(parseHoldPressedPayload(payload)).toEqual({
      inject_eligible: false,
      target_hwnd: 0,
    });
  });
});
