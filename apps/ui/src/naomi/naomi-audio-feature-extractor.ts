/**
 * Audio → pool drive (brief §3): per-frame features from a Web Audio
 * AnalyserNode tap — RMS envelope with the emotion engine's attack/decay,
 * band energies (low 0–300Hz swell, mid 300–2k rim ripple, high 2k–8k fine
 * texture), and half-wave-rectified spectral flux for syllable pulses.
 *
 * Split in two for testability: computeAudioFrameFeatures is PURE (buffers
 * in, features out — property/boundary testable with synthetic signals);
 * NaomiAnalyserTap is the thin AnalyserNode plumbing around it. fftSize 1024,
 * smoothingTimeConstant 0 — physics smoothing is ours, not the browser's.
 */

import type { AudioFrameFeatures } from "./naomi-pool-uniforms";

export const ANALYSER_FFT_SIZE = 1024;

/** Mutable carry-over between frames (envelope memory + previous spectrum). */
export interface AudioFeatureState {
  envelope: number;
  previousSpectrum: Float32Array;
}

export function createAudioFeatureState(binCount: number = ANALYSER_FFT_SIZE / 2): AudioFeatureState {
  return { envelope: 0, previousSpectrum: new Float32Array(binCount) };
}

function bandMean(spectrum: Uint8Array, fromHz: number, toHz: number, binHz: number): number {
  const first = Math.max(0, Math.floor(fromHz / binHz));
  const last = Math.min(spectrum.length - 1, Math.ceil(toHz / binHz));
  if (last < first) return 0;
  let sum = 0;
  for (let i = first; i <= last; i++) sum += spectrum[i] ?? 0;
  return sum / ((last - first + 1) * 255); // normalise byte bins → 0..1
}

/**
 * Pure per-frame feature computation.
 *
 * @param timeDomain  float samples −1..1 (AnalyserNode.getFloatTimeDomainData)
 * @param spectrum    byte frequency bins (AnalyserNode.getByteFrequencyData)
 * @param sampleRate  the AudioContext rate (24000 for the Naomi voice path)
 * @param attack      envelope attack lerp 0..1 (emotion-driven, e.g. 0.5)
 * @param decay       envelope decay multiplier 0..1 (e.g. 0.93)
 * @param state       mutated in place: envelope memory + previous spectrum
 */
export function computeAudioFrameFeatures(
  timeDomain: Float32Array,
  spectrum: Uint8Array,
  sampleRate: number,
  attack: number,
  decay: number,
  state: AudioFeatureState,
): AudioFrameFeatures {
  // RMS of the time-domain buffer — the raw loudness this frame.
  let sumSquares = 0;
  for (let i = 0; i < timeDomain.length; i++) {
    const sample = timeDomain[i] ?? 0;
    sumSquares += sample * sample;
  }
  const rms = timeDomain.length === 0 ? 0 : Math.sqrt(sumSquares / timeDomain.length);
  // House waveform physics (design brief §8): fast attack toward louder
  // targets, damped multiplicative decay when the sound falls away.
  const target = Math.min(1, rms * 2.5); // speech RMS ~0.2–0.4 → usable 0..1
  state.envelope =
    target > state.envelope
      ? state.envelope + (target - state.envelope) * attack
      : state.envelope * decay;

  const binHz = sampleRate / 2 / spectrum.length;
  const low = bandMean(spectrum, 0, 300, binHz);
  const mid = bandMean(spectrum, 300, 2000, binHz);
  const high = bandMean(spectrum, 2000, 8000, binHz);

  // Spectral flux: half-wave-rectified positive change vs the previous
  // frame — spikes at syllable onsets, silent during steady tones.
  let flux = 0;
  const prev = state.previousSpectrum;
  const bins = Math.min(spectrum.length, prev.length);
  for (let i = 0; i < bins; i++) {
    const bin = (spectrum[i] ?? 0) / 255;
    const rise = bin - (prev[i] ?? 0);
    if (rise > 0) flux += rise;
    prev[i] = bin;
  }
  flux = Math.min(1, bins === 0 ? 0 : (flux / bins) * 12); // scaled to ~0..1 for speech

  return { envelope: state.envelope, low, mid, high, flux };
}

/**
 * The live AnalyserNode tap. One instance serves BOTH drives — Naomi's own
 * voice (playback graph) and the dev screen's mic toggle — whichever source
 * is currently connected. Buffers are pre-allocated (zero rAF allocations).
 */
export class NaomiAnalyserTap {
  readonly analyser: AnalyserNode;
  private readonly timeDomain: Float32Array<ArrayBuffer>;
  private readonly spectrum: Uint8Array<ArrayBuffer>;
  private readonly state: AudioFeatureState;
  private readonly sampleRate: number;

  constructor(context: AudioContext) {
    this.analyser = context.createAnalyser();
    this.analyser.fftSize = ANALYSER_FFT_SIZE;
    this.analyser.smoothingTimeConstant = 0; // physics smoothing is ours
    this.timeDomain = new Float32Array(this.analyser.fftSize);
    this.spectrum = new Uint8Array(this.analyser.frequencyBinCount);
    this.state = createAudioFeatureState(this.analyser.frequencyBinCount);
    this.sampleRate = context.sampleRate;
  }

  /** Sample one frame of features using the emotion engine's envelope knobs. */
  sample(attack: number, decay: number): AudioFrameFeatures {
    this.analyser.getFloatTimeDomainData(this.timeDomain);
    this.analyser.getByteFrequencyData(this.spectrum);
    return computeAudioFrameFeatures(
      this.timeDomain,
      this.spectrum,
      this.sampleRate,
      attack,
      decay,
      this.state,
    );
  }
}
