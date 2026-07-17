import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { Mic, AudioLines, MessageSquareText, FileAudio, ArrowRight } from "lucide-react";
import { OmniButton } from "../components/button";
import { appSettingsStore } from "../lib/settings-store";
import { meetingsStore, loadMeetings } from "../lib/meetings-store";
import { createLiveMeetingsRepository } from "../lib/meetings-live-repository";
import { pickMediaFile } from "../lib/pick-media-file";
import { importMediaFile } from "../lib/meetings-live-repository";
import { openMeetingDetail, meetingsDetailStore } from "../lib/meetings-detail-store";
import { requestSetupCommand } from "../lib/setup-settings-transport";
import { formatDayLabel, formatDurationMin } from "../lib/format-quantities";
import { useMicLevelPercent } from "../lib/use-mic-level-percent";
import { localPrivacyCopy } from "./home-privacy-copy";

interface HomeScreenProps {
  readonly onNavigate: (sectionId: "library" | "live" | "ask" | "dictation" | "settings") => void;
  readonly onStartCapture: () => void;
  /** Keyboard Voice Replacement → open dictation and start the inline recorder. */
  readonly onRecordInline?: () => void;
}

interface DictationHistoryEntry {
  readonly id: number;
  readonly created_at: string;
  readonly mode: string;
  readonly raw_text: string;
  readonly cleaned_text: string | null;
  readonly note_title: string | null;
}

export function HomeScreen({ onNavigate, onStartCapture, onRecordInline }: HomeScreenProps) {
  const settings = useStore(appSettingsStore, (s) => s.settings);
  const meetings = useStore(meetingsStore, (s) => s.meetings);

  const [dictations, setDictations] = useState<readonly DictationHistoryEntry[]>([]);
  const [dictationError, setDictationError] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const microphone = useStore(appSettingsStore, (s) => s.microphone);
  const { level: micLevel, micActive } = useMicLevelPercent(true, microphone);

  const identity = settings?.speakerIdentity?.trim();
  const userName = identity && identity.length > 0 ? identity : "there";

  // Load meetings & dictation history
  useEffect(() => {
    const repo = createLiveMeetingsRepository();
    void loadMeetings(meetingsStore, repo);

    void requestSetupCommand("dictation.history.list", { limit: 3 })
      .then((payload) => {
        const list = payload["entries"];
        if (Array.isArray(list)) {
          setDictations(list as DictationHistoryEntry[]);
          setDictationError(null);
        }
      })
      .catch(() => {
        setDictationError("Could not load recent voice notes.");
      });
  }, []);

  const triggerImport = async () => {
    setImportError(null);
    const path = await pickMediaFile();
    if (path === null) return;
    setImportBusy(true);
    try {
      const meetingId = await importMediaFile(path, undefined, { identifySpeakers: false });
      const repo = createLiveMeetingsRepository();
      await loadMeetings(meetingsStore, repo);
      openMeetingDetail(meetingsDetailStore, meetingId);
      onNavigate("library");
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setImportBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto" style={{ padding: "48px 64px 56px" }}>
      {/* Header */}
      <header className="flex flex-col gap-2">
        <h1
          className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
          style={{
            fontSize: "var(--text-page-size)",
            lineHeight: "var(--text-page-lh)",
            letterSpacing: "var(--text-page-ls)",
          }}
        >
          Welcome back, {userName}
        </h1>
        <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-body-size)" }}>
          {localPrivacyCopy(settings).body}
        </p>
      </header>

      {/* Quick Action Grid */}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-6 max-w-[960px]">
        {/* Record Meeting */}
        <div className="flex flex-col justify-between p-5 border border-[var(--grey-200)] rounded-[var(--radius-card)] bg-[var(--canvas)] hover:border-[var(--accent)] hover:shadow-float transition-all duration-[var(--dur-micro)]">
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <div className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-control)] bg-[var(--grey-50)] text-[var(--accent)]">
                <Mic size={20} />
              </div>
              {micActive && (
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[var(--accent-muted)] border border-[var(--accent-border)]">
                  <div className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-pulse" />
                  <span className="text-[10px] font-medium text-[var(--accent)] font-mono">
                    MIC OK
                  </span>
                </div>
              )}
            </div>
            <div className="flex flex-col gap-1">
              <h2 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 16 }}>
                Record a Meeting
              </h2>
              <p className="m-0 text-[var(--ink-secondary)] text-sm leading-relaxed">
                Transcribe and summarize discussions in real-time. Fuses your notes with full multi-speaker transcripts.
              </p>
            </div>
          </div>
          
          <div className="mt-6 flex flex-col gap-3">
            {micActive && (
              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between text-[11px] font-mono text-[var(--ink-secondary)]">
                  <span>Microphone volume</span>
                  <span>{micLevel}%</span>
                </div>
                <div className="h-1.5 bg-[var(--grey-200)] rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-[var(--accent)] rounded-full transition-all duration-75"
                    style={{ width: `${micLevel}%` }}
                  />
                </div>
              </div>
            )}
            <OmniButton variant="primary" className="w-full" onClick={onStartCapture}>
              Start Capture
            </OmniButton>
          </div>
        </div>

        {/* Dictate Voice Note */}
        <div className="flex flex-col justify-between p-5 border border-[var(--grey-200)] rounded-[var(--radius-card)] bg-[var(--canvas)] hover:border-[var(--accent)] hover:shadow-float transition-all duration-[var(--dur-micro)]">
          <div className="flex flex-col gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-control)] bg-[var(--grey-50)] text-[var(--accent)]">
              <AudioLines size={20} />
            </div>
            <div className="flex flex-col gap-1">
              <h2 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 16 }}>
                Keyboard Voice Replacement
              </h2>
              <p className="m-0 text-[var(--ink-secondary)] text-sm leading-relaxed">
                Replace typing with voice. Dictate instantly into Slack, Word, or emails by holding F9.
              </p>
            </div>
          </div>
          <div className="mt-6 flex gap-2">
            <OmniButton variant="secondary" className="flex-1" onClick={() => onNavigate("dictation")}>
              View Notes
            </OmniButton>
            <OmniButton
              variant="primary"
              className="flex-1"
              onClick={() => {
                if (onRecordInline !== undefined) {
                  onRecordInline();
                  return;
                }
                // Fallback when App does not wire auto-start: open dictation.
                onNavigate("dictation");
              }}
            >
              Record Inline
            </OmniButton>
          </div>
        </div>

        {/* Ask Omni */}
        <div className="flex flex-col justify-between p-5 border border-[var(--grey-200)] rounded-[var(--radius-card)] bg-[var(--canvas)] hover:border-[var(--accent)] hover:shadow-float transition-all duration-[var(--dur-micro)]">
          <div className="flex flex-col gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-control)] bg-[var(--grey-50)] text-[var(--accent)]">
              <MessageSquareText size={20} />
            </div>
            <div className="flex flex-col gap-1">
              <h2 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 16 }}>
                Ask Across Notes
              </h2>
              <p className="m-0 text-[var(--ink-secondary)] text-sm leading-relaxed">
                Query meetings, summaries, and action items using natural language.
              </p>
            </div>
          </div>
          <div className="mt-6">
            <OmniButton variant="secondary" className="w-full" onClick={() => onNavigate("ask")}>
              Ask a Question
            </OmniButton>
          </div>
        </div>

        {/* Import Media */}
        <div className="flex flex-col justify-between p-5 border border-[var(--grey-200)] rounded-[var(--radius-card)] bg-[var(--canvas)] hover:border-[var(--accent)] hover:shadow-float transition-all duration-[var(--dur-micro)]">
          <div className="flex flex-col gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-control)] bg-[var(--grey-50)] text-[var(--accent)]">
              <FileAudio size={20} />
            </div>
            <div className="flex flex-col gap-1">
              <h2 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 16 }}>
                Import Audio File
              </h2>
              <p className="m-0 text-[var(--ink-secondary)] text-sm leading-relaxed">
                Upload MP3, WAV, or MP4 files recorded elsewhere to transcribe and structure them locally.
              </p>
            </div>
          </div>
          <div className="mt-6 flex flex-col gap-2">
            {importError && (
              <span className="text-[11px] text-[var(--error-text)] font-mono">
                {importError}
              </span>
            )}
            <OmniButton variant="secondary" className="w-full" loading={importBusy} onClick={triggerImport}>
              {importBusy ? "Importing…" : "Choose File"}
            </OmniButton>
          </div>
        </div>
      </div>

      {/* Recents and Help Section */}
      <div className="mt-12 grid grid-cols-1 lg:grid-cols-3 gap-8 max-w-[960px]">
        {/* Recents */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          <h3 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 16 }}>
            Recent Activity
          </h3>
          <div className="flex flex-col border border-[var(--grey-200)] rounded-[var(--radius-card)] divide-y divide-[var(--grey-200)] overflow-hidden">
            {meetings.slice(0, 2).map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => {
                  openMeetingDetail(meetingsDetailStore, m.id);
                  onNavigate("library");
                }}
                className="flex items-center justify-between p-4 bg-transparent border-0 cursor-pointer text-left hover:bg-[var(--grey-50)] transition-colors w-full"
              >
                <div className="flex flex-col gap-0.5">
                  <span className="font-semibold text-sm text-[var(--ink)] truncate max-w-[280px]">
                    {m.title}
                  </span>
                  <span className="text-xs text-[var(--ink-secondary)] font-mono">
                    Meeting · {formatDayLabel(m.startIso)}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-[var(--ink-secondary)] font-mono">
                  <span>{formatDurationMin(m.durationMin)}</span>
                  <ArrowRight size={14} />
                </div>
              </button>
            ))}

            {dictationError && (
              <p role="alert" className="m-0 text-[var(--error-text)]" style={{ fontSize: 12 }}>
                {dictationError}
              </p>
            )}
            {dictations.slice(0, 2).map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => onNavigate("dictation")}
                className="flex items-center justify-between p-4 bg-transparent border-0 cursor-pointer text-left hover:bg-[var(--grey-50)] transition-colors w-full"
              >
                <div className="flex flex-col gap-0.5">
                  <span className="font-semibold text-sm text-[var(--ink)] truncate max-w-[280px]">
                    {d.cleaned_text?.trim() || d.raw_text}
                  </span>
                  <span className="text-xs text-[var(--ink-secondary)] font-mono">
                    Voice Note · {d.created_at}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-[var(--ink-secondary)] font-mono">
                  <span>{d.mode}</span>
                  <ArrowRight size={14} />
                </div>
              </button>
            ))}

            {meetings.length === 0 && dictations.length === 0 && (
              <div className="p-8 text-center text-sm text-[var(--ink-secondary)]">
                No recent activity. Start recording a meeting or voice note!
              </div>
            )}
          </div>
        </div>

        {/* Help Panel */}
        <div className="flex flex-col gap-4">
          <h3 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 16 }}>
            How to Use
          </h3>
          <div className="flex flex-col gap-4 p-5 border border-[var(--grey-200)] rounded-[var(--radius-card)] bg-[var(--grey-50)]">
            <div className="flex items-start gap-2.5">
              <span className="text-sm">💡</span>
              <div className="flex flex-col gap-0.5">
                <span className="text-xs font-semibold text-[var(--ink)]">Type anywhere with voice</span>
                <span className="text-xs text-[var(--ink-secondary)] leading-relaxed">
                  Hold F9 in any application (like Slack or emails) to transcribe and type directly with your voice.
                </span>
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <span className="text-sm">🔒</span>
              <div className="flex flex-col gap-0.5">
                <span className="text-xs font-semibold text-[var(--ink)]">
                  {localPrivacyCopy(settings).title}
                </span>
                <span className="text-xs text-[var(--ink-secondary)] leading-relaxed">
                  {localPrivacyCopy(settings).body}
                </span>
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <span className="text-sm">📁</span>
              <div className="flex flex-col gap-0.5">
                <span className="text-xs font-semibold text-[var(--ink)]"> vault Storage</span>
                <span className="text-xs text-[var(--ink-secondary)] leading-relaxed">
                  Your notes are saved in your vault folder as standard Markdown files, making them portable and future-proof.
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
