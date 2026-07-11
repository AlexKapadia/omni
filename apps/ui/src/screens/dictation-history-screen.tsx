import { useEffect, useState, useRef } from "react";
import { Square, Plus, Search, AudioLines } from "lucide-react";
import { requestSetupCommand } from "../lib/setup-settings-transport";
import { OmniButton } from "../components/button";
import { subscribeToEngineFrames, sendEngineCommand } from "../lib/live-engine-socket";
import { parseInboundMessage } from "../lib/protocol";
import {
  parseDictationPartialPayload,
  parseDictationFinalPayload,
  parseDictationErrorPayload,
} from "../pill/dictation-events-protocol";
import { formatMeetingClock } from "../lib/transcript-store";

export interface DictationHistoryEntry {
  readonly id: number;
  readonly created_at: string;
  readonly mode: string;
  readonly raw_text: string;
  readonly cleaned_text: string | null;
  readonly note_title: string | null;
}

export function DictationHistoryScreen() {
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<readonly DictationHistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Recording State
  const [isRecording, setIsRecording] = useState(false);
  const [duration, setDuration] = useState(0);
  const [partialText, setPartialText] = useState("");
  const [recordingError, setRecordingError] = useState<string | null>(null);

  const durationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const [waveHeights, setWaveHeights] = useState<number[]>([10, 10, 10, 10, 10, 10, 10, 10]);

  const load = async (search: string): Promise<void> => {
    try {
      const payload = await requestSetupCommand("dictation.history.list", {
        ...(search.trim() ? { query: search.trim() } : {}),
        limit: 100,
      });
      const list = payload["entries"];
      if (!Array.isArray(list)) {
        setError("Could not load dictation history.");
        return;
      }
      setEntries(list as DictationHistoryEntry[]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load dictation history.");
    }
  };

  useEffect(() => {
    void load("");
  }, []);

  // Always listen for dictation.final (F9 / pill) so history stays fresh even
  // when the inline recorder is idle. Partial/error stay recorder-scoped.
  const isRecordingRef = useRef(isRecording);
  isRecordingRef.current = isRecording;

  useEffect(() => {
    const unsubscribe = subscribeToEngineFrames((data) => {
      const result = parseInboundMessage(data);
      if (!result.ok || result.envelope.kind !== "event") return;
      const { name, payload } = result.envelope;

      if (name === "dictation.partial") {
        if (!isRecordingRef.current) return;
        const parsed = parseDictationPartialPayload(payload);
        if (parsed !== null) {
          setPartialText(parsed.text);
        }
      } else if (name === "dictation.final") {
        const parsed = parseDictationFinalPayload(payload);
        if (parsed !== null) {
          if (isRecordingRef.current) {
            stopRecordingState();
          }
          void load(query);
        }
      } else if (name === "dictation.cancel") {
        // Pill/F9 cancel — no list change; keep subscription alive.
      } else if (name === "dictation.error") {
        if (!isRecordingRef.current) return;
        const parsed = parseDictationErrorPayload(payload);
        if (parsed !== null) {
          setRecordingError(parsed.reason);
          stopRecordingState();
        }
      }
    });

    return () => {
      unsubscribe();
    };
  }, [query]);

  const startRecording = async () => {
    setRecordingError(null);
    setPartialText("");
    setDuration(0);

    const ok = sendEngineCommand("dictation.begin");
    if (!ok) {
      setRecordingError("Omni Steroid is offline — dictation is unavailable.");
      return;
    }

    setIsRecording(true);
    durationTimerRef.current = setInterval(() => {
      setDuration((d) => d + 1);
    }, 1000);

    // Waveform simulation using Web Audio APIs
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      const ctx = new AudioContextClass();
      audioContextRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 32;
      analyserRef.current = analyser;
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const updateWave = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(dataArray);
        const newHeights = Array.from(dataArray)
          .slice(0, 8)
          .map((v) => Math.max(8, Math.round((v / 255) * 48)));
        setWaveHeights(newHeights);
        animationFrameRef.current = requestAnimationFrame(updateWave);
      };
      updateWave();
    } catch {
      // Honest idle waveform — never invent mic activity.
      setWaveHeights([10, 10, 10, 10, 10, 10, 10, 10]);
      setRecordingError((prev) => prev ?? "Microphone unavailable for the waveform preview.");
    }
  };

  const stopRecordingState = () => {
    setIsRecording(false);
    if (durationTimerRef.current !== null) {
      clearInterval(durationTimerRef.current);
      durationTimerRef.current = null;
    }
    if (animationFrameRef.current !== null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      void audioContextRef.current.close();
      audioContextRef.current = null;
    }
    setWaveHeights([10, 10, 10, 10, 10, 10, 10, 10]);
  };

  const saveRecording = () => {
    const ok = sendEngineCommand("dictation.end", { inject_requested: false });
    if (!ok) {
      setRecordingError("Omni Steroid is offline — could not save the voice note.");
      stopRecordingState();
    }
    // On success, wait for dictation.final / dictation.error to stop UI.
  };

  const cancelRecording = () => {
    // Abort without finalize — Cancel must not write a note.
    const ok = sendEngineCommand("dictation.cancel");
    stopRecordingState();
    if (!ok) {
      setRecordingError("Omni Steroid is offline — recording stopped locally.");
    }
  };

  return (
    <div className="flex flex-col gap-6 p-12 max-w-[960px] mx-auto h-full overflow-y-auto">
      {/* Header and Action */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1.5">
          <h1 className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-page-size)" }}>
            Voice notes
          </h1>
          <p className="m-0 text-sm text-[var(--ink-secondary)]">
            Speak quick thoughts to save them as cleaned-up, searchable notes on this device.
          </p>
        </div>
        {!isRecording && (
          <OmniButton variant="primary" icon={Plus} onClick={startRecording}>
            Record Note
          </OmniButton>
        )}
      </div>

      {/* Inline Dictation Recorder Panel */}
      {isRecording && (
        <div className="p-6 border-2 border-[var(--accent)] rounded-[var(--radius-card)] bg-[var(--canvas)] flex flex-col gap-5 shadow-float animate-fade-in">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-[var(--live)] animate-pulse" />
              <span className="text-xs font-semibold text-[var(--live-strong)] font-mono">
                RECORDING DICTATION
              </span>
            </div>
            <span className="text-xs font-mono text-[var(--ink)] bg-[var(--grey-50)] px-2 py-1 rounded">
              {formatMeetingClock(duration)}
            </span>
          </div>

          {/* Animated Waveform Visualizer */}
          <div className="flex items-center justify-center gap-1.5 h-16 bg-[var(--grey-50)] rounded-[var(--radius-control)]">
            {waveHeights.map((h, i) => (
              <div
                key={i}
                className="w-1.5 rounded-full bg-[var(--accent)] transition-all duration-75"
                style={{ height: `${h}px` }}
              />
            ))}
          </div>

          {/* Live Transcript Preview Box */}
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-mono text-[var(--ink-secondary)] uppercase">Live Transcript</span>
            <div className="p-4 border border-[var(--grey-200)] rounded-[var(--radius-control)] bg-[var(--canvas)] min-h-[64px] max-h-[128px] overflow-y-auto">
              {partialText ? (
                <p className="m-0 text-sm text-[var(--ink)] leading-relaxed italic">
                  {partialText}
                </p>
              ) : (
                <span className="text-xs text-[var(--grey-600)] italic">
                  Start speaking...
                </span>
              )}
            </div>
          </div>

          {/* Recorder Actions */}
          <div className="flex justify-end gap-2 pt-2 border-t border-[var(--grey-200)]">
            <OmniButton variant="ghost" onClick={cancelRecording}>
              Cancel
            </OmniButton>
            <OmniButton variant="primary" icon={Square} onClick={saveRecording}>
              Done & Save
            </OmniButton>
          </div>
        </div>
      )}

      {/* Search Filter */}
      {!isRecording && (
        <form
          className="relative flex items-center"
          onSubmit={(e) => {
            e.preventDefault();
            void load(query);
          }}
        >
          <Search size={16} className="absolute left-[var(--control-padding-x)] text-[var(--ink-secondary)] shrink-0" />
          <input
            aria-label="Search dictations"
            className="w-full omni-input"
            style={{ paddingLeft: "calc(var(--control-padding-x) + 24px)" }}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search past dictations"
          />
        </form>
      )}

      {recordingError && (
        <div className="p-3 border border-[var(--error)] bg-[var(--error-bg)] text-[var(--error-text)] text-xs rounded-[var(--radius-control)]">
          {recordingError}
        </div>
      )}

      {error !== null && <p className="text-[var(--error-text)] font-mono text-sm">{error}</p>}

      {error === null && !isRecording && entries.length === 0 ? (
        <div
          role="status"
          aria-label="No voice notes yet"
          className="mt-[var(--space-6)] flex flex-col items-center text-center gap-[var(--space-4)] p-8 border border-[var(--grey-200)] border-dashed rounded-[var(--radius-card)]"
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--grey-50)] text-[var(--grey-400)]">
            <AudioLines size={24} />
          </div>
          <div className="flex flex-col gap-1">
            <h2 className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]" style={{ fontSize: 16 }}>
              No voice notes yet
            </h2>
            <p className="m-0 text-[var(--ink-secondary)] text-sm leading-relaxed max-w-sm">
              Click "Record Note" at the top to speak a quick thought, or Hold F9 anywhere to capture a thought.
            </p>
          </div>
        </div>
      ) : (
        !isRecording && (
          <ul className="m-0 list-none p-0 flex flex-col gap-3">
            {entries.map((entry) => (
              <li
                key={entry.id}
                className="p-4 border border-[var(--grey-200)] rounded-[var(--radius-card)] bg-[var(--canvas)] hover:border-[var(--grey-600)] transition-colors flex flex-col gap-2"
              >
                <div className="flex items-center justify-between text-xs text-[var(--ink-secondary)] font-mono">
                  <span>{entry.created_at}</span>
                  <span className="uppercase text-[10px] bg-[var(--grey-50)] px-2 py-0.5 rounded">
                    {entry.mode}
                  </span>
                </div>
                <p className="m-0 text-sm text-[var(--ink)] leading-relaxed">
                  {entry.cleaned_text?.trim() || entry.raw_text}
                </p>
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
}

