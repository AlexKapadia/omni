/**
 * Barge-in state machine: interruption at EVERY phase, stale-context audio
 * refusal, and the ramp lifecycle — Naomi must be silenceable in 20ms and
 * must never play audio from a cancelled utterance (brief §7).
 */
import { describe, expect, it } from "vitest";
import {
  BARGE_IN_RAMP_SECONDS,
  NaomiBargeInStateMachine,
} from "./naomi-bargein-state-machine";

describe("happy path", () => {
  it("idle → playing on first chunk; done returns to idle", () => {
    const m = new NaomiBargeInStateMachine();
    expect(m.currentPhase).toBe("idle");
    expect(m.onChunk("ctx-1")).toEqual({ kind: "schedule-chunk" });
    expect(m.currentPhase).toBe("playing");
    expect(m.onDone("ctx-1")).toEqual({ kind: "finish" });
    expect(m.currentPhase).toBe("idle");
    expect(m.contextId).toBeNull();
  });

  it("many chunks of one context all schedule", () => {
    const m = new NaomiBargeInStateMachine();
    for (let i = 0; i < 50; i++) {
      expect(m.onChunk("ctx-1").kind).toBe("schedule-chunk");
    }
  });
});

describe("barge-in at every phase", () => {
  it("while playing: starts the 20ms ramp", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    expect(m.onBargeIn()).toEqual({ kind: "start-ramp-down", rampSeconds: BARGE_IN_RAMP_SECONDS });
    expect(m.currentPhase).toBe("ducking");
  });

  it("while idle: a no-op (nothing is sounding)", () => {
    const m = new NaomiBargeInStateMachine();
    expect(m.onBargeIn()).toEqual({ kind: "none" });
    expect(m.currentPhase).toBe("idle");
  });

  it("while already ducking: a second barge-in is a no-op, not a double ramp", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    m.onBargeIn();
    expect(m.onBargeIn()).toEqual({ kind: "none" });
  });

  it("ramp completion finishes and clears the context", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    m.onBargeIn();
    expect(m.onRampComplete()).toEqual({ kind: "finish" });
    expect(m.currentPhase).toBe("idle");
    expect(m.contextId).toBeNull();
  });

  it("ramp completion in any other phase is a no-op", () => {
    const m = new NaomiBargeInStateMachine();
    expect(m.onRampComplete()).toEqual({ kind: "none" });
    m.onChunk("ctx-1");
    expect(m.onRampComplete()).toEqual({ kind: "none" });
    expect(m.currentPhase).toBe("playing"); // untouched
  });
});

describe("stale audio can NEVER sound (fail closed)", () => {
  it("chunks arriving during the duck are dropped", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    m.onBargeIn();
    expect(m.onChunk("ctx-1")).toEqual({ kind: "drop-chunk", reason: "ducking" });
    expect(m.onChunk("ctx-2")).toEqual({ kind: "drop-chunk", reason: "ducking" });
  });

  it("chunks from a DIFFERENT context than the active one are dropped", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    expect(m.onChunk("ctx-OLD")).toEqual({ kind: "drop-chunk", reason: "stale-context" });
    expect(m.currentPhase).toBe("playing"); // the live utterance is unaffected
  });

  it("a stale done (wrong context) does not stop the live utterance", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    expect(m.onDone("ctx-OLD")).toEqual({ kind: "none" });
    expect(m.currentPhase).toBe("playing");
  });

  it("done during ducking defers to the ramp's cleanup (no double finish)", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    m.onBargeIn();
    expect(m.onDone("ctx-1")).toEqual({ kind: "none" });
    expect(m.currentPhase).toBe("ducking"); // still owned by the ramp
  });
});

describe("new utterance semantics", () => {
  it("a new utterance over a playing one triggers the ramp (implicit barge-in)", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    expect(m.onNewUtterance("ctx-2")).toEqual({
      kind: "start-ramp-down",
      rampSeconds: BARGE_IN_RAMP_SECONDS,
    });
    expect(m.currentPhase).toBe("ducking");
  });

  it("a new utterance from idle simply claims the context", () => {
    const m = new NaomiBargeInStateMachine();
    expect(m.onNewUtterance("ctx-1")).toEqual({ kind: "none" });
    expect(m.contextId).toBe("ctx-1");
    expect(m.onChunk("ctx-1").kind).toBe("schedule-chunk");
  });

  it("full interrupt cycle: play → new utterance → ramp → new context plays", () => {
    const m = new NaomiBargeInStateMachine();
    m.onChunk("ctx-1");
    m.onNewUtterance("ctx-2");
    expect(m.onChunk("ctx-2").kind).toBe("drop-chunk"); // still ducking
    m.onRampComplete();
    expect(m.onChunk("ctx-2").kind).toBe("schedule-chunk"); // now clean
    expect(m.contextId).toBe("ctx-2");
  });
});
