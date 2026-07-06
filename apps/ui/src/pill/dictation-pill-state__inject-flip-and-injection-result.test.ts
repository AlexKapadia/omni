/**
 * Inject disposition in the pill state machine: arming at keydown, the
 * flip-to-note affordance (only before release), the wake word overriding
 * the INSERT chip, injection-result tracking in the result phase, and the
 * stale-event guards that keep an old paste outcome off a new session.
 * Pure reducer — no React, no Tauri, no socket.
 */
import { describe, expect, it } from "vitest";

import type { DictationFinalPayload } from "./dictation-events-protocol";
import {
  IDLE_PILL_STATE,
  formatLatencyMs,
  reduceDictationPill,
  type DictationPillEvent,
  type DictationPillState,
} from "./dictation-pill-state";

function run(events: DictationPillEvent[], from: DictationPillState = IDLE_PILL_STATE) {
  return events.reduce(reduceDictationPill, from);
}

const INJECT_FINAL: DictationFinalPayload = {
  mode: "inject",
  text: "um send the report",
  cleaned_text: "Send the report.",
  cleanup_source: "model",
  cleanup_latency_ms: 412,
  flush_ms: 96,
};

const NOTE_FINAL: DictationFinalPayload = { mode: "note", text: "buy milk" };

describe("inject arming at keydown", () => {
  it("injectEligible arms INSERT for the session", () => {
    const state = run([{ type: "hold-pressed", atMs: 0, injectEligible: true }]);
    expect(state).toMatchObject({ phase: "listening", injectArmed: true });
  });

  it("absent or false eligibility stays on the safe note path", () => {
    expect(run([{ type: "hold-pressed", atMs: 0 }])).toMatchObject({ injectArmed: false });
    expect(
      run([{ type: "hold-pressed", atMs: 0, injectEligible: false }]),
    ).toMatchObject({ injectArmed: false });
  });

  it("arming carries through release into processing", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0, injectEligible: true },
      { type: "partial", text: "send the report" },
      { type: "hold-released" },
    ]);
    expect(state).toMatchObject({ phase: "processing", injectArmed: true });
  });

  it("a NEW hold re-decides eligibility from ITS keydown, not the last one", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0, injectEligible: true },
      { type: "hold-released" },
      { type: "hold-pressed", atMs: 50 }, // no eligibility this time
    ]);
    expect(state).toMatchObject({ phase: "listening", injectArmed: false });
  });
});

describe("flip-to-note affordance", () => {
  it("flips INSERT back to NOTE while listening", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0, injectEligible: true },
      { type: "flip-to-note" },
    ]);
    expect(state).toMatchObject({ phase: "listening", injectArmed: false });
  });

  it("the flip is one-way within a session (no re-arm event exists)", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0, injectEligible: true },
      { type: "flip-to-note" },
      { type: "hold-released" },
    ]);
    expect(state).toMatchObject({ phase: "processing", injectArmed: false });
  });

  it("flip after release is ignored — the disposition already shipped", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0, injectEligible: true },
      { type: "hold-released" },
      { type: "flip-to-note" },
    ]);
    expect(state).toMatchObject({ phase: "processing", injectArmed: true });
  });

  it("flip in idle/result/error is a no-op", () => {
    expect(run([{ type: "flip-to-note" }])).toEqual(IDLE_PILL_STATE);
    const inResult = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "hold-released" },
      { type: "final", payload: NOTE_FINAL },
      { type: "flip-to-note" },
    ]);
    expect(inResult.phase).toBe("result");
  });

  it("wake word and INSERT coexist in state; command wins at render/send", () => {
    // The reducer keeps both flags; the bridge sends inject_requested only
    // when commandDetected is false, and the engine's split is authoritative.
    const state = run([
      { type: "hold-pressed", atMs: 0, injectEligible: true },
      { type: "partial", text: "Omni, schedule lunch" },
    ]);
    expect(state).toMatchObject({ commandDetected: true, injectArmed: true });
  });
});

describe("injection-result tracking", () => {
  const toInjectResult: DictationPillEvent[] = [
    { type: "hold-pressed", atMs: 0, injectEligible: true },
    { type: "hold-released" },
    { type: "final", payload: INJECT_FINAL, totalMs: 1042 },
  ];

  it("an inject final opens the result with a PENDING injection + total", () => {
    const state = run(toInjectResult);
    expect(state).toEqual({
      phase: "result",
      final: INJECT_FINAL,
      totalMs: 1042,
      injection: { status: "pending" },
    });
  });

  it("a note final has NO injection leg", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "hold-released" },
      { type: "final", payload: NOTE_FINAL },
    ]);
    expect(state).toEqual({ phase: "result", final: NOTE_FINAL });
  });

  it("a successful paste lands with its real elapsed ms", () => {
    const state = run([
      ...toInjectResult,
      { type: "injection-result", ok: true, elapsedMs: 361 },
    ]);
    expect(state).toMatchObject({
      injection: { status: "done", elapsedMs: 361 },
    });
  });

  it("a failed paste lands with its honest reason", () => {
    const state = run([
      ...toInjectResult,
      {
        type: "injection-result",
        ok: false,
        reason: "target app runs elevated (admin) — text left on the clipboard",
      },
    ]);
    expect(state).toMatchObject({
      injection: {
        status: "failed",
        reason: "target app runs elevated (admin) — text left on the clipboard",
      },
    });
  });

  it("a second injection-result cannot overwrite a settled outcome", () => {
    const state = run([
      ...toInjectResult,
      { type: "injection-result", ok: true, elapsedMs: 361 },
      { type: "injection-result", ok: false, reason: "late ghost" },
    ]);
    expect(state).toMatchObject({ injection: { status: "done", elapsedMs: 361 } });
  });

  it("an injection-result after a NEW hold is dropped (stale guard)", () => {
    const state = run([
      ...toInjectResult,
      { type: "hold-pressed", atMs: 99 }, // user is already dictating again
      { type: "injection-result", ok: false, reason: "stale" },
    ]);
    expect(state).toMatchObject({ phase: "listening", startedAtMs: 99 });
  });

  it("injection-result in idle or on a note result is a no-op", () => {
    expect(run([{ type: "injection-result", ok: true, elapsedMs: 5 }])).toEqual(
      IDLE_PILL_STATE,
    );
    const noteResult = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "hold-released" },
      { type: "final", payload: NOTE_FINAL },
      { type: "injection-result", ok: true, elapsedMs: 5 },
    ]);
    expect(noteResult).toEqual({ phase: "result", final: NOTE_FINAL });
  });
});

describe("latency label formatting (exact — the shown numbers are real)", () => {
  it.each([
    [0, "0 ms"],
    [999, "999 ms"], // just under the unit switch
    [1000, "1.00 s"], // exactly at it
    [1042, "1.04 s"],
    [812.4, "812 ms"], // rounds, never truncates dishonestly
    [-5, "0 ms"], // clock skew never shows negative speed
  ])("%d ms -> %s", (ms, expected) => {
    expect(formatLatencyMs(ms)).toBe(expected);
  });
});
