/**
 * Real microphone levels for the pill waveform via getUserMedia + an
 * AnalyserNode. The waveform must be "driven by real levels" (design §8) —
 * never synthetic animation.
 *
 * Privacy note: this analyser NEVER records or transmits audio — it reads
 * instantaneous time-domain levels for the visual only; transcription audio
 * is captured independently by the engine (and discarded after STT).
 */

export interface MicrophoneLevelSource {
  /** Copy the current time-domain snapshot into `target`; false if stopped. */
  readTimeDomain(target: Uint8Array<ArrayBuffer>): boolean;
  stop(): void;
}

/**
 * Open the default microphone for level metering. Throws when permission is
 * denied or no device exists — the caller renders the inactive waveform
 * honestly instead of a fake one.
 */
export async function openMicrophoneLevelSource(): Promise<MicrophoneLevelSource> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 256; // 128 time-domain samples — plenty for 20 bars
  analyser.smoothingTimeConstant = 0; // raw levels; OUR attack/decay shapes them
  source.connect(analyser);
  let stopped = false;
  return {
    readTimeDomain(target: Uint8Array<ArrayBuffer>): boolean {
      if (stopped) return false;
      analyser.getByteTimeDomainData(target);
      return true;
    },
    stop(): void {
      if (stopped) return;
      stopped = true;
      source.disconnect();
      for (const track of stream.getTracks()) track.stop(); // release the mic
      void context.close();
    },
  };
}
