/**
 * Streaming playout of Naomi's voice: engine-relayed Cartesia PCM
 * (pcm_f32le @ 24kHz) → gapless scheduled AudioBufferSourceNodes → GainNode
 * (the 20ms barge-in ramp) → destination, with the AnalyserNode tap that
 * drives the pool — Naomi's voice literally moves the water (brief §3).
 *
 * WHY scheduled buffers instead of an AudioWorklet ring buffer for the dev
 * loop: chunk-accurate scheduling on one AudioContext clock is gapless,
 * needs no worklet module loading, and keeps this file pure TypeScript; the
 * worklet upgrade rides with the full conversation loop (M2/M3) where
 * sub-quantum latency starts to matter.
 *
 * The pure playback decisions live in naomi-bargein-state-machine.ts; this
 * class only executes the actions it returns.
 */

import { NaomiAnalyserTap } from "./naomi-audio-feature-extractor";
import {
  BARGE_IN_RAMP_SECONDS,
  NaomiBargeInStateMachine,
} from "./naomi-bargein-state-machine";

/** Cartesia output contract (engine pins pcm_f32le @ 24000 Hz). */
export const NAOMI_VOICE_SAMPLE_RATE = 24000;

/** Decode one base64 pcm_f32le payload into samples. Fail closed: malformed
 *  base64 or a byte length that is not a whole number of floats → null. */
export function decodePcmFloat32Base64(b64: string): Float32Array | null {
  let binary: string;
  try {
    binary = atob(b64);
  } catch {
    return null;
  }
  if (binary.length === 0 || binary.length % 4 !== 0) return null;
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const samples = new Float32Array(bytes.buffer);
  // A hostile payload could decode to Inf/NaN and slam the speakers —
  // refuse any chunk containing a non-finite or out-of-range sample.
  for (let i = 0; i < samples.length; i++) {
    const sample = samples[i] ?? Number.NaN;
    if (!Number.isFinite(sample) || Math.abs(sample) > 4) return null;
  }
  return samples;
}

export class NaomiVoicePlayback {
  private readonly context: AudioContext;
  private readonly gain: GainNode;
  readonly analyserTap: NaomiAnalyserTap;
  readonly machine = new NaomiBargeInStateMachine();
  private scheduledSources: AudioBufferSourceNode[] = [];
  private nextStartTime = 0;
  private rampTimer: ReturnType<typeof setTimeout> | null = null;
  /** Called when an utterance fully finishes or is barged in. */
  onPlaybackFinished: (() => void) | null = null;

  constructor(context?: AudioContext) {
    this.context =
      context ?? new AudioContext({ sampleRate: NAOMI_VOICE_SAMPLE_RATE });
    this.gain = this.context.createGain();
    this.analyserTap = new NaomiAnalyserTap(this.context);
    // Voice path: sources → gain → analyser tap → speakers. The analyser
    // sits AFTER the gain so a barged-in (silenced) voice also stills the
    // water — what you hear is what the pool shows.
    this.gain.connect(this.analyserTap.analyser);
    this.analyserTap.analyser.connect(this.context.destination);
  }

  /** Feed one decoded PCM chunk belonging to `contextId`. */
  enqueueChunk(contextId: string, samples: Float32Array): boolean {
    const action = this.machine.onChunk(contextId);
    if (action.kind !== "schedule-chunk") return false;
    void this.context.resume(); // autoplay policies: resume on real audio
    const buffer = this.context.createBuffer(1, samples.length, NAOMI_VOICE_SAMPLE_RATE);
    buffer.copyToChannel(new Float32Array(samples), 0);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gain);
    // Gapless scheduling: each chunk starts exactly where the previous ends
    // (with a tiny safety lead on the very first chunk of an utterance).
    const now = this.context.currentTime;
    const startAt = Math.max(now + 0.01, this.nextStartTime);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;
    this.scheduledSources.push(source);
    source.onended = () => {
      this.scheduledSources = this.scheduledSources.filter((s) => s !== source);
    };
    return true;
  }

  /** The engine says this utterance is complete. */
  handleDone(contextId: string): void {
    const action = this.machine.onDone(contextId);
    if (action.kind === "finish") this.onPlaybackFinished?.();
  }

  /** Barge-in: 20ms gain ramp to zero, then flush every scheduled source. */
  bargeIn(): void {
    const action = this.machine.onBargeIn();
    if (action.kind !== "start-ramp-down") return;
    const now = this.context.currentTime;
    this.gain.gain.cancelScheduledValues(now);
    this.gain.gain.setValueAtTime(this.gain.gain.value, now);
    this.gain.gain.linearRampToValueAtTime(0, now + action.rampSeconds);
    if (this.rampTimer !== null) clearTimeout(this.rampTimer);
    this.rampTimer = setTimeout(() => {
      this.flushAndReset();
      const finish = this.machine.onRampComplete();
      if (finish.kind === "finish") this.onPlaybackFinished?.();
    }, BARGE_IN_RAMP_SECONDS * 1000 + 5);
  }

  /** A new utterance is starting: silence any previous one first. */
  beginUtterance(contextId: string): void {
    const action = this.machine.onNewUtterance(contextId);
    if (action.kind === "start-ramp-down") this.bargeInForNewUtterance(action.rampSeconds);
  }

  private bargeInForNewUtterance(rampSeconds: number): void {
    const now = this.context.currentTime;
    this.gain.gain.cancelScheduledValues(now);
    this.gain.gain.setValueAtTime(this.gain.gain.value, now);
    this.gain.gain.linearRampToValueAtTime(0, now + rampSeconds);
    if (this.rampTimer !== null) clearTimeout(this.rampTimer);
    this.rampTimer = setTimeout(() => {
      this.flushAndReset();
      this.machine.onRampComplete();
    }, rampSeconds * 1000 + 5);
  }

  private flushAndReset(): void {
    for (const source of this.scheduledSources) {
      try {
        source.stop();
      } catch {
        /* already ended — flushing is idempotent */
      }
    }
    this.scheduledSources = [];
    this.nextStartTime = 0;
    // Restore gain for the next utterance (the ramp only silences THIS one).
    this.gain.gain.cancelScheduledValues(this.context.currentTime);
    this.gain.gain.setValueAtTime(1, this.context.currentTime);
  }

  /** Route an external source (dev-screen mic) through the SAME analyser. */
  connectExternalSource(node: AudioNode): void {
    node.connect(this.analyserTap.analyser);
  }

  get audioContext(): AudioContext {
    return this.context;
  }
}
