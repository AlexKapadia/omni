/**
 * Pill state machine: hold/release ordering, "Omni," vs "omnibus" chip
 * behaviour, release-before-speech, double-press, and stale-event guards.
 * Pure reducer — no React, no Tauri, no socket.
 */
import { describe, expect, it } from "vitest";

import type { DictationFinalPayload } from "./dictation-events-protocol";
import {
  IDLE_PILL_STATE,
  formatHoldTimer,
  reduceDictationPill,
  type DictationPillEvent,
  type DictationPillState,
} from "./dictation-pill-state";

function run(events: DictationPillEvent[], from: DictationPillState = IDLE_PILL_STATE) {
  return events.reduce(reduceDictationPill, from);
}

const NOTE_FINAL: DictationFinalPayload = {
  mode: "note",
  text: "buy milk",
  note_path: "C:/vault/Inbox/Buy milk.md",
  note_title: "Buy milk",
  title_source: "model",
};

describe("hold / release lifecycle", () => {
  it("hold starts a fresh listening session (note mode by default)", () => {
    const state = run([{ type: "hold-pressed", atMs: 1000 }]);
    expect(state).toEqual({
      phase: "listening",
      startedAtMs: 1000,
      liveText: "",
      commandDetected: false,
      injectArmed: false, // no eligibility flag -> the safe path: a note
    });
  });

  it("release moves to processing, keeping the live text", () => {
    const state = run([
      { type: "hold-pressed", atMs: 1000 },
      { type: "partial", text: "buy milk" },
      { type: "hold-released" },
    ]);
    expect(state.phase).toBe("processing");
    expect(state).toMatchObject({ liveText: "buy milk" });
  });

  it("release before any speech still awaits the engine's (empty) final", () => {
    const state = run([{ type: "hold-pressed", atMs: 0 }, { type: "hold-released" }]);
    expect(state).toMatchObject({ phase: "processing", liveText: "" });
  });

  it("a stray keyup in idle is ignored", () => {
    expect(run([{ type: "hold-released" }])).toEqual(IDLE_PILL_STATE);
  });

  it("double-press restarts a clean session from ANY phase", () => {
    for (const prelude of [
      [] as DictationPillEvent[],
      [{ type: "hold-pressed", atMs: 1 } as const],
      [{ type: "hold-pressed", atMs: 1 } as const, { type: "hold-released" } as const],
      [
        { type: "hold-pressed", atMs: 1 } as const,
        { type: "hold-released" } as const,
        { type: "final", payload: NOTE_FINAL } as const,
      ],
      [{ type: "hold-pressed", atMs: 1 } as const, { type: "error", reason: "x" } as const],
    ]) {
      const state = run([...prelude, { type: "hold-pressed", atMs: 99 }]);
      expect(state).toEqual({
        phase: "listening",
        startedAtMs: 99,
        liveText: "",
        commandDetected: false,
        injectArmed: false,
      });
    }
  });
});

describe("command detection on partials", () => {
  it('flips the chip on an "Omni," prefix', () => {
    const state = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "partial", text: "Omni, schedule lunch" },
    ]);
    expect(state).toMatchObject({ commandDetected: true });
  });

  it('does NOT flip on "omnibus" — the wake word must be the whole word', () => {
    const state = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "partial", text: "omnibus schedules are confusing" },
    ]);
    expect(state).toMatchObject({ commandDetected: false });
  });

  it("re-evaluates on every partial (early misfire corrects itself)", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "partial", text: "Omni" },
      { type: "partial", text: "omnibus timetables" },
    ]);
    expect(state).toMatchObject({ commandDetected: false });
  });

  it("a late partial during processing updates the echo, not the phase", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "hold-released" },
      { type: "partial", text: "Omni, last words" },
    ]);
    expect(state).toMatchObject({ phase: "processing", commandDetected: true });
  });

  it("partials in idle/result are dropped (stale guard)", () => {
    expect(run([{ type: "partial", text: "ghost" }])).toEqual(IDLE_PILL_STATE);
    const result = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "hold-released" },
      { type: "final", payload: NOTE_FINAL },
      { type: "partial", text: "ghost" },
    ]);
    expect(result.phase).toBe("result");
  });
});

describe("finals, errors, dismissal", () => {
  it("final lands only while processing", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "hold-released" },
      { type: "final", payload: NOTE_FINAL },
    ]);
    expect(state).toEqual({ phase: "result", final: NOTE_FINAL });
  });

  it("a stale final must NOT clobber a new hold", () => {
    const state = run([
      { type: "hold-pressed", atMs: 0 },
      { type: "hold-released" },
      { type: "hold-pressed", atMs: 50 }, // user pressed again before final
      { type: "final", payload: NOTE_FINAL },
    ]);
    expect(state.phase).toBe("listening"); // the new session survives
  });

  it("final in idle is dropped", () => {
    expect(run([{ type: "final", payload: NOTE_FINAL }])).toEqual(IDLE_PILL_STATE);
  });

  it("errors surface from listening and processing, not idle/result", () => {
    expect(
      run([{ type: "hold-pressed", atMs: 0 }, { type: "error", reason: "engine offline" }]),
    ).toEqual({ phase: "error", reason: "engine offline" });
    expect(run([{ type: "error", reason: "ghost" }])).toEqual(IDLE_PILL_STATE);
  });

  it("dismiss returns to idle from every phase", () => {
    for (const prelude of [
      [{ type: "hold-pressed", atMs: 0 } as const],
      [
        { type: "hold-pressed", atMs: 0 } as const,
        { type: "hold-released" } as const,
        { type: "final", payload: NOTE_FINAL } as const,
      ],
      [{ type: "hold-pressed", atMs: 0 } as const, { type: "error", reason: "x" } as const],
    ]) {
      expect(run([...prelude, { type: "dismiss" }])).toEqual(IDLE_PILL_STATE);
    }
  });
});

describe("timer formatting (exact)", () => {
  it.each([
    [0, "00:00"],
    [999, "00:00"], // just under one second
    [1000, "00:01"], // exactly one second
    [59_999, "00:59"], // just under a minute
    [60_000, "01:00"], // exactly a minute
    [61_500, "01:01"],
    [3_599_000, "59:59"],
    [-5, "00:00"], // clock skew never shows negative time
  ])("%d ms -> %s", (ms, expected) => {
    expect(formatHoldTimer(ms)).toBe(expected);
  });
});
