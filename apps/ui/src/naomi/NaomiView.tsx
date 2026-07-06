/**
 * The Naomi screen (brief §4): the pool full-bleed on the white canvas —
 * NAOMI label top-left, the living water centered at 46% viewport height,
 * caption line beneath — plus the development tuning drawer that drives
 * every input live (presets, sliders, mic, say/cancel, FPS + tier readout).
 *
 * Owns the lifecycles: pool renderer (tier ladder + rAF), the dedicated
 * voice socket, and the Web Audio playback graph whose AnalyserNode is the
 * same one that moves the water — Naomi's voice IS the drive signal.
 */

import { useEffect, useRef, useState } from "react";
import { clampAffect, type Affect, IDLE_AFFECT } from "./naomi-affect-types";
import { NaomiDevTuningDrawer } from "./naomi-dev-tuning-drawer";
import { NaomiEngineVoiceSocket } from "./naomi-engine-voice-socket";
import { decodePcmFloat32Base64, NaomiVoicePlayback } from "./naomi-audio-playback";
import { NaomiPoolRenderer, type RendererStats } from "./naomi-pool-renderer";

declare global {
  interface Window {
    /** Dev-build test hook (brief §5 measurement plan). */
    __naomi?: { setAffect: (v: number, a: number, burst: number) => void };
  }
}

export function NaomiView() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<NaomiPoolRenderer | null>(null);
  const playbackRef = useRef<NaomiVoicePlayback | null>(null);
  const socketRef = useRef<NaomiEngineVoiceSocket | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const sayDispatchedAtRef = useRef<number | null>(null);

  const [affect, setAffect] = useState<Affect>(IDLE_AFFECT);
  const [micEnabled, setMicEnabled] = useState(false);
  const [stats, setStats] = useState<RendererStats | null>(null);
  const [engineConnected, setEngineConnected] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttfaMs, setTtfaMs] = useState<number | null>(null);
  const [caption, setCaption] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  // Lazily build the audio graph (AudioContext wants a user gesture first).
  const ensurePlayback = (): NaomiVoicePlayback => {
    if (playbackRef.current === null) {
      const playback = new NaomiVoicePlayback();
      playback.onPlaybackFinished = () => setSpeaking(false);
      playbackRef.current = playback;
      rendererRef.current?.setAudioSampler((attack, decay) =>
        playback.analyserTap.sample(attack, decay),
      );
    }
    return playbackRef.current;
  };

  // Renderer lifecycle: probe tiers, size to the stage, run the loop.
  useEffect(() => {
    const canvas = canvasRef.current;
    const stage = stageRef.current;
    if (canvas === null || stage === null) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const renderer = new NaomiPoolRenderer(canvas, reducedMotion);
    rendererRef.current = renderer;
    const measure = () => {
      const rect = stage.getBoundingClientRect();
      renderer.resize(rect.width, rect.height, window.devicePixelRatio);
    };
    measure();
    renderer.start();
    // Brief §4: resize via ResizeObserver debounced 100ms.
    let debounce: ReturnType<typeof setTimeout> | null = null;
    const observer = new ResizeObserver(() => {
      if (debounce !== null) clearTimeout(debounce);
      debounce = setTimeout(measure, 100);
    });
    observer.observe(stage);
    const statsTimer = setInterval(() => setStats(renderer.stats), 500);
    if (import.meta.env.DEV) {
      window.__naomi = {
        setAffect: (v, a, burst) =>
          renderer.setAffect(clampAffect(v, a, burst > 0 ? { kind: "laugh", intensity: burst } : null)),
      };
    }
    return () => {
      observer.disconnect();
      clearInterval(statsTimer);
      renderer.stop();
      rendererRef.current = null;
      delete window.__naomi;
    };
  }, []);

  // Voice socket lifecycle: dedicated connection for the naomi.* surface.
  useEffect(() => {
    const socket = new NaomiEngineVoiceSocket({
      onConnectionChange: setEngineConnected,
      onErrorReply: (message) => {
        setLastError(message);
        setSpeaking(false);
      },
      onAudioChunk: (chunk) => {
        const samples = decodePcmFloat32Base64(chunk.pcm_b64);
        if (samples === null) return; // fail closed on corrupt audio
        const playback = ensurePlayback();
        playback.beginUtterance(chunk.context_id);
        if (playback.enqueueChunk(chunk.context_id, samples)) {
          setSpeaking(true);
          if (chunk.ttfa_ms !== null) setTtfaMs(chunk.ttfa_ms);
          else if (chunk.seq === 0 && sayDispatchedAtRef.current !== null) {
            // Round-trip TTFA as observed from the UI (honest, measured).
            setTtfaMs(performance.now() - sayDispatchedAtRef.current);
          }
        }
      },
      onAudioDone: (done) => {
        playbackRef.current?.handleDone(done.context_id);
        if (done.reason === "error") setLastError(done.detail ?? "voice generation failed");
      },
      onTimestamps: (stamps) => setCaption(stamps.words.join(" ")),
    });
    socketRef.current = socket;
    socket.connect();
    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyAffect = (valence: number, arousal: number, laugh: boolean) => {
    const next = clampAffect(valence, arousal, laugh ? { kind: "laugh", intensity: 1 } : null);
    setAffect(next);
    rendererRef.current?.setAffect(next);
  };

  const toggleMic = async () => {
    if (micEnabled) {
      micStreamRef.current?.getTracks().forEach((track) => track.stop());
      micStreamRef.current = null;
      setMicEnabled(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const playback = ensurePlayback();
      const source = playback.audioContext.createMediaStreamSource(stream);
      playback.connectExternalSource(source);
      void playback.audioContext.resume();
      micStreamRef.current = stream;
      setMicEnabled(true);
      setLastError(null);
    } catch {
      setLastError("Microphone unavailable — permission denied or no device.");
    }
  };

  const handleSay = (text: string) => {
    ensurePlayback(); // user gesture: safe moment to create the AudioContext
    setLastError(null);
    setTtfaMs(null);
    sayDispatchedAtRef.current = performance.now();
    const sent = socketRef.current?.say(text, {
      v: affect.valence,
      a: affect.arousal,
      burst: affect.burst === null ? null : "laugh",
    });
    if (sent !== true) setLastError("The engine is offline. Voice needs the engine running.");
  };

  const handleCancel = () => {
    playbackRef.current?.bargeIn(); // perceived stop <50ms, locally first
    socketRef.current?.cancel(); // then stop generation at the source
    setSpeaking(false);
  };

  return (
    <div className="flex h-full flex-col bg-[var(--canvas)]">
      <div ref={stageRef} className="relative min-h-0 flex-1">
        <p
          className="absolute m-0"
          style={{
            top: "var(--space-12)", left: "var(--space-12)",
            fontFamily: "var(--font-mono)", fontSize: 11,
            letterSpacing: "var(--label-ls)", textTransform: "uppercase",
            color: "var(--grey-400)",
          }}
        >
          Naomi
        </p>
        {/* The water. Full-bleed canvas; the pool geometry (44vmin clamp,
            46% optical center) is composed inside the shader's coordinate
            space via the stage-sized canvas. */}
        <canvas
          ref={canvasRef}
          data-testid="naomi-pool-canvas"
          aria-label="Naomi — a pool of black water that moves as she listens and speaks"
          role="img"
          className="absolute inset-0 h-full w-full"
        />
        {caption !== null && (
          <p
            className="absolute left-1/2 m-0 -translate-x-1/2 text-center"
            style={{
              top: "78%", maxWidth: 560,
              fontFamily: "var(--font-body)", fontSize: 15, fontWeight: 400,
              color: "var(--grey-600)",
            }}
          >
            {caption}
          </p>
        )}
      </div>
      <NaomiDevTuningDrawer
        valence={affect.valence}
        arousal={affect.arousal}
        onAffectChange={applyAffect}
        micEnabled={micEnabled}
        onMicToggle={() => void toggleMic()}
        stats={stats}
        engineConnected={engineConnected}
        ttfaMs={ttfaMs}
        speaking={speaking}
        lastError={lastError}
        onSay={handleSay}
        onCancel={handleCancel}
      />
    </div>
  );
}
