/**
 * Shared live mic level (0–100) for Home / Live / Settings meters.
 * Permission denial or missing mediaDevices → inactive + level 0 (honest).
 *
 * Optional ``engineMicId`` is a PortAudio key (`{index}:{name}`). The browser
 * deviceId is different — we match by label/name when possible, else default.
 */
import { useEffect, useRef, useState } from "react";

/** Extract the device name from a PortAudio `{index}:{name}` key. */
export function micNameFromEngineId(engineMicId: string | undefined): string {
  if (!engineMicId || !engineMicId.trim()) return "";
  const colon = engineMicId.indexOf(":");
  if (colon < 0) return engineMicId.trim();
  return engineMicId.slice(colon + 1).trim();
}

async function resolveBrowserAudioConstraint(
  engineMicId: string | undefined,
): Promise<boolean | MediaTrackConstraints> {
  const name = micNameFromEngineId(engineMicId);
  if (!name || !navigator.mediaDevices.enumerateDevices) {
    return true;
  }
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const needle = name.toLowerCase();
    const match = devices.find(
      (d) =>
        d.kind === "audioinput" &&
        d.deviceId &&
        d.label &&
        (d.label.toLowerCase() === needle || d.label.toLowerCase().includes(needle)),
    );
    if (match) {
      return { deviceId: { exact: match.deviceId } };
    }
  } catch {
    // Fall through to default mic.
  }
  return true;
}

export function useMicLevelPercent(
  active: boolean,
  engineMicId?: string,
): {
  readonly level: number;
  readonly micActive: boolean;
} {
  const [level, setLevel] = useState(0);
  const [micActive, setMicActive] = useState(false);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      setLevel(0);
      setMicActive(false);
      return;
    }
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setMicActive(false);
      setLevel(0);
      return;
    }

    let cancelled = false;
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;

    void (async () => {
      const audio = await resolveBrowserAudioConstraint(engineMicId);
      if (cancelled) return;
      try {
        const s = await navigator.mediaDevices.getUserMedia({ audio });
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        stream = s;
        setMicActive(true);
        const AudioContextClass =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        context = new AudioContextClass();
        const source = context.createMediaStreamSource(s);
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const tick = (): void => {
          analyser.getByteFrequencyData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) sum += data[i] ?? 0;
          setLevel(Math.min(100, Math.round((sum / data.length / 255) * 100)));
          rafRef.current = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        if (!cancelled) {
          setMicActive(false);
          setLevel(0);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      stream?.getTracks().forEach((t) => t.stop());
      void context?.close();
    };
  }, [active, engineMicId]);

  return { level, micActive };
}
