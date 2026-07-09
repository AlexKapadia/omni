import type { ChangeEvent } from "react";

export function StepSpeakerIdentity({
  name,
  onChangeName,
}: {
  readonly name: string;
  readonly onChangeName: (name: string) => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <h2
        className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
        style={{ fontSize: "var(--text-section-size)", lineHeight: "var(--text-section-lh)" }}
      >
        What's your name?
      </h2>
      <p className="mt-[var(--space-2)] mb-0 text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-body-size)" }}>
        We'll label your voice in transcripts so you can tell speakers apart.
      </p>

      <div className="mt-[var(--space-6)] flex flex-col gap-[var(--space-2)]">
        <label className="block text-[var(--ink-secondary)] font-medium" style={{ fontSize: 12 }} htmlFor="speaker-name-input">
          Your name
        </label>
        <input
          id="speaker-name-input"
          type="text"
          className="w-full omni-input"
          placeholder="e.g. Alex"
          value={name}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onChangeName(e.target.value)}
        />
      </div>
    </div>
  );
}
