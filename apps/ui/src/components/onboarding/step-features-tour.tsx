import { Mic, AudioLines, MessageSquareText } from "lucide-react";

interface FeatureRowProps {
  readonly icon: typeof Mic;
  readonly title: string;
  readonly description: string;
}

function FeatureRow({ icon: Icon, title, description }: FeatureRowProps) {
  return (
    <div className="flex gap-4 p-4 border border-[var(--grey-200)] rounded-[var(--radius-card)] hover:border-[var(--accent)] hover:bg-[var(--accent-subtle)] transition-all duration-[var(--dur-micro)]">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-control)] bg-[var(--grey-50)] text-[var(--accent)]">
        <Icon size={20} strokeWidth={2} />
      </div>
      <div className="flex flex-col gap-1">
        <h3 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 15 }}>
          {title}
        </h3>
        <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: 13, lineHeight: 1.5 }}>
          {description}
        </p>
      </div>
    </div>
  );
}

export function StepFeaturesTour({ onContinue }: { readonly onContinue: () => void }) {
  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div className="flex flex-col gap-2">
        <h2 className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-section-size)" }}>
          What Omni Steroid can do
        </h2>
        <p className="m-0 text-[var(--ink-secondary)] animate-fade-in" style={{ fontSize: "var(--text-body-size)" }}>
          Omni Steroid runs entirely on your device. Here are the core tools you'll be using:
        </p>
      </div>

      <div className="flex flex-col gap-4">
        <FeatureRow
          icon={Mic}
          title="Record Meetings"
          description="Capture in-room audio and system output. Transcribe them on-device and auto-generate clean summaries and action items."
        />
        <FeatureRow
          icon={AudioLines}
          title="Keyboard Voice Replacement"
          description="Type with your voice anywhere on your computer. Hold the F9 hotkey to dictate text directly into Slack, Word, or emails, fully cleaned up."
        />
        <FeatureRow
          icon={MessageSquareText}
          title="Ask Omni"
          description="Query across all your meetings, transcripts, and notes. Ask natural questions to retrieve specific details instantly."
        />
      </div>
    </div>
  );
}
