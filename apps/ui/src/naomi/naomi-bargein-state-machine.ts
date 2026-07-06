/**
 * Playback / barge-in state machine (brief §7): the pure decision core the
 * audio playback layer obeys. Naomi's speech is interruptible at ANY moment;
 * an interruption ramps gain to zero in 20ms, flushes queued audio, and the
 * machine refuses to play stale chunks from a cancelled utterance.
 *
 * Pure and synchronous — every transition is exactly unit-testable; the Web
 * Audio side effects live in naomi-audio-playback.ts and simply follow the
 * actions this machine returns.
 */

/** How long the barge-in gain ramp takes (brief: perceived stop < 50ms). */
export const BARGE_IN_RAMP_SECONDS = 0.02;

export type PlaybackPhase = "idle" | "playing" | "ducking";

export type PlaybackAction =
  | { readonly kind: "schedule-chunk" }
  | { readonly kind: "drop-chunk"; readonly reason: "stale-context" | "ducking" }
  | { readonly kind: "start-ramp-down"; readonly rampSeconds: number }
  | { readonly kind: "finish" }
  | { readonly kind: "none" };

export class NaomiBargeInStateMachine {
  private phase: PlaybackPhase = "idle";
  private activeContextId: string | null = null;

  get currentPhase(): PlaybackPhase {
    return this.phase;
  }

  get contextId(): string | null {
    return this.activeContextId;
  }

  /** An audio chunk arrived for `contextId` — play it or refuse it. */
  onChunk(contextId: string): PlaybackAction {
    if (this.phase === "ducking") {
      // Chunks racing in after a barge-in belong to the interrupted
      // utterance — they must NEVER sound (fail closed on stale audio).
      return { kind: "drop-chunk", reason: "ducking" };
    }
    if (this.activeContextId !== null && this.activeContextId !== contextId) {
      return { kind: "drop-chunk", reason: "stale-context" };
    }
    this.activeContextId = contextId;
    this.phase = "playing";
    return { kind: "schedule-chunk" };
  }

  /** The user barged in (or cancel was pressed). */
  onBargeIn(): PlaybackAction {
    if (this.phase !== "playing") return { kind: "none" }; // nothing sounding
    this.phase = "ducking";
    return { kind: "start-ramp-down", rampSeconds: BARGE_IN_RAMP_SECONDS };
  }

  /** The 20ms ramp completed; buffers were flushed. */
  onRampComplete(): PlaybackAction {
    if (this.phase !== "ducking") return { kind: "none" };
    this.phase = "idle";
    this.activeContextId = null;
    return { kind: "finish" };
  }

  /** The engine reported the utterance finished (naomi.audio.done). */
  onDone(contextId: string): PlaybackAction {
    if (this.activeContextId !== contextId) return { kind: "none" }; // stale done
    if (this.phase === "ducking") return { kind: "none" }; // ramp owns cleanup
    this.phase = "idle";
    this.activeContextId = null;
    return { kind: "finish" };
  }

  /** A brand-new utterance begins: barge-in semantics against the old one. */
  onNewUtterance(contextId: string): PlaybackAction {
    if (this.phase === "playing" && this.activeContextId !== contextId) {
      this.phase = "ducking";
      return { kind: "start-ramp-down", rampSeconds: BARGE_IN_RAMP_SECONDS };
    }
    if (this.phase === "idle") this.activeContextId = contextId;
    return { kind: "none" };
  }
}
