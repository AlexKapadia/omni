import { useStore } from "zustand";
import { OnboardingModelProgressRow } from "./onboarding-model-progress-row";
import { modelsPresent, type OnboardingFlowStore } from "../../lib/onboarding-flow-store";

export function StepModels({
  store,
  selectedEngine,
  setSelectedEngine,
  selectedSummaryModel,
  setSelectedSummaryModel,
}: {
  readonly store: OnboardingFlowStore;
  readonly selectedEngine: "parakeet" | "whisper";
  readonly setSelectedEngine: (engine: "parakeet" | "whisper") => void;
  readonly selectedSummaryModel: string;
  readonly setSelectedSummaryModel: (model: string) => void;
}) {
  const started = useStore(store, (s) => s.modelsStarted);
  const files = useStore(store, (s) => s.modelFiles);
  const present = useStore(store, modelsPresent);
  const modelsOk = useStore(store, (s) => s.modelsOk);

  const hasFailure = modelsOk === false || files.some((f) => f.failedMessage !== null);

  const select = (engine: "parakeet" | "whisper") => {
    if (!started && !present) {
      setSelectedEngine(engine);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <h2
        className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
        style={{
          fontSize: "var(--text-title-size)",
          lineHeight: "var(--text-title-lh)",
          letterSpacing: "var(--text-title-ls)",
        }}
      >
        Choose your transcription engine
      </h2>
      <p
        className="mt-[var(--space-2)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)" }}
      >
        Pick how Omni Steroid processes your audio. You can change this later in Settings.
      </p>

      {/* Two-tier selection cards */}
      <div className="mt-[var(--space-6)] flex flex-col gap-[var(--space-4)]">
        {/* Tier 1 Card: Fast & Light */}
        <div
          onClick={() => select("parakeet")}
          className={`flex flex-col border rounded-[var(--radius-card)] p-[var(--space-4)] transition-all duration-[var(--dur-micro)] ${
            started || present ? "cursor-default" : "cursor-pointer hover:shadow-[var(--shadow-float)]"
          }`}
          style={{
            backgroundColor: selectedEngine === "parakeet" ? "var(--accent-muted)" : "var(--canvas)",
            borderColor: selectedEngine === "parakeet" ? "var(--accent)" : "var(--grey-200)",
            borderWidth: selectedEngine === "parakeet" ? 2 : 1,
            padding: selectedEngine === "parakeet" ? "15px 15px" : "16px 16px", // Account for border width offset
          }}
        >
          <div className="flex items-start gap-[var(--space-3)]">
            <div
              className="flex items-center justify-center rounded-[var(--radius-control)] w-8 h-8"
              style={{
                backgroundColor: selectedEngine === "parakeet" ? "var(--accent)" : "var(--grey-50)",
                color: selectedEngine === "parakeet" ? "var(--on-accent)" : "var(--grey-600)",
              }}
            >
              {/* Lucide Zap Icon */}
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
            </div>
            <div className="flex-1 flex flex-col">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-emphasis-size)" }}>
                  Fast & Light (Recommended)
                </span>
                <span className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
                  ~2.5 GB download
                </span>
              </div>
              <span className="text-[var(--ink-secondary)] mt-0.5" style={{ fontSize: "var(--text-body-size)" }}>
                Good accuracy, low resource usage
              </span>
            </div>
            {selectedEngine === "parakeet" && (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ color: "var(--accent)", marginLeft: "auto" }}
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </div>
          {/* Progress bar inside the active card */}
          {selectedEngine === "parakeet" && (started || files.length > 0) && (
            <div className="mt-[var(--space-4)] border-t border-[var(--grey-200)] pt-[var(--space-2)]">
              {files.map((file) => (
                <OnboardingModelProgressRow key={file.file} file={file} />
              ))}
            </div>
          )}
        </div>

        {/* Tier 2 Card: Accurate & Powerful */}
        <div
          onClick={() => select("whisper")}
          className={`flex flex-col border rounded-[var(--radius-card)] p-[var(--space-4)] transition-all duration-[var(--dur-micro)] ${
            started || present ? "cursor-default" : "cursor-pointer hover:shadow-[var(--shadow-float)]"
          }`}
          style={{
            backgroundColor: selectedEngine === "whisper" ? "var(--accent-muted)" : "var(--canvas)",
            borderColor: selectedEngine === "whisper" ? "var(--accent)" : "var(--grey-200)",
            borderWidth: selectedEngine === "whisper" ? 2 : 1,
            padding: selectedEngine === "whisper" ? "15px 15px" : "16px 16px",
          }}
        >
          <div className="flex items-start gap-[var(--space-3)]">
            <div
              className="flex items-center justify-center rounded-[var(--radius-control)] w-8 h-8"
              style={{
                backgroundColor: selectedEngine === "whisper" ? "var(--accent)" : "var(--grey-50)",
                color: selectedEngine === "whisper" ? "var(--on-accent)" : "var(--grey-600)",
              }}
            >
              {/* Lucide BrainCircuit Icon */}
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 5V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1Z" />
                <path d="M18 19v-2a1 1 0 0 0-1-1h-2a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1Z" />
                <path d="M12 13v-2a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1Z" />
                <path d="M14 6.5h1.5a2.5 2.5 0 0 1 2.5 2.5v2" />
                <path d="M10 13H8a2 2 0 0 0-2 2v2" />
                <path d="M10 6.5H8.5A2.5 2.5 0 0 0 6 9v2" />
                <path d="M14 13h1.5a1.5 1.5 0 0 1 1.5 1.5v1.5" />
              </svg>
            </div>
            <div className="flex-1 flex flex-col">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-emphasis-size)" }}>
                  Accurate & Powerful
                </span>
                <span className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
                  ~3.1 GB download
                </span>
              </div>
              <span className="text-[var(--ink-secondary)] mt-0.5" style={{ fontSize: "var(--text-body-size)" }}>
                Best accuracy, uses more resources
              </span>
            </div>
            {selectedEngine === "whisper" && (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ color: "var(--accent)", marginLeft: "auto" }}
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </div>
          {/* Progress bar inside the active card */}
          {selectedEngine === "whisper" && (started || files.length > 0) && (
            <div className="mt-[var(--space-4)] border-t border-[var(--grey-200)] pt-[var(--space-2)]">
              {files.map((file) => (
                <OnboardingModelProgressRow key={file.file} file={file} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Summary Model Selection */}
      <h3
        className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)] mt-6"
        style={{
          fontSize: "var(--text-section-size)",
          lineHeight: "var(--text-section-lh)",
          letterSpacing: "var(--text-section-ls)",
        }}
      >
        Choose your summary & analysis model
      </h3>
      <p
        className="mt-[var(--space-1)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-meta-size)" }}
      >
        Select the default AI model used for summarizing meetings and processing prompts.
      </p>

      <div className="mt-[var(--space-4)] flex flex-col gap-[var(--space-3)]">
        {/* Gemini 1.5 Flash */}
        <div
          onClick={() => setSelectedSummaryModel("gemini-2.5-flash")}
          className="flex flex-col border rounded-[var(--radius-card)] p-[var(--space-3)] transition-all duration-[var(--dur-micro)] cursor-pointer hover:shadow-[var(--shadow-float)]"
          style={{
            backgroundColor: selectedSummaryModel === "gemini-2.5-flash" ? "var(--accent-muted)" : "var(--canvas)",
            borderColor: selectedSummaryModel === "gemini-2.5-flash" ? "var(--accent)" : "var(--grey-200)",
            borderWidth: selectedSummaryModel === "gemini-2.5-flash" ? 2 : 1,
            padding: selectedSummaryModel === "gemini-2.5-flash" ? "11px 11px" : "12px 12px",
          }}
        >
          <div className="flex items-center gap-[var(--space-3)]">
            <div
              className="flex items-center justify-center rounded-[var(--radius-control)] w-8 h-8 shrink-0"
              style={{
                backgroundColor: selectedSummaryModel === "gemini-2.5-flash" ? "var(--accent)" : "var(--grey-50)",
                color: selectedSummaryModel === "gemini-2.5-flash" ? "var(--on-accent)" : "var(--grey-600)",
              }}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275Z"/>
                <path d="m5 3 1 2.5L8.5 6 6 7 5 9.5 4 7 1.5 6 4 5.5Z"/>
                <path d="m19 17 1 2.5 2.5.5-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1Z"/>
              </svg>
            </div>
            <div className="flex-1 flex flex-col">
              <span className="font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
                Gemini 2.5 Flash (Fast & Balanced)
              </span>
              <span className="text-[var(--ink-secondary)] mt-0.5" style={{ fontSize: "var(--text-meta-size)" }}>
                Optimized for speed and efficiency. Ideal for standard notes.
              </span>
            </div>
            {selectedSummaryModel === "gemini-2.5-flash" && (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ color: "var(--accent)" }}
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </div>
        </div>

        {/* Gemini 1.5 Pro */}
        <div
          onClick={() => setSelectedSummaryModel("gemini-2.5-pro")}
          className="flex flex-col border rounded-[var(--radius-card)] p-[var(--space-3)] transition-all duration-[var(--dur-micro)] cursor-pointer hover:shadow-[var(--shadow-float)]"
          style={{
            backgroundColor: selectedSummaryModel === "gemini-2.5-pro" ? "var(--accent-muted)" : "var(--canvas)",
            borderColor: selectedSummaryModel === "gemini-2.5-pro" ? "var(--accent)" : "var(--grey-200)",
            borderWidth: selectedSummaryModel === "gemini-2.5-pro" ? 2 : 1,
            padding: selectedSummaryModel === "gemini-2.5-pro" ? "11px 11px" : "12px 12px",
          }}
        >
          <div className="flex items-center gap-[var(--space-3)]">
            <div
              className="flex items-center justify-center rounded-[var(--radius-control)] w-8 h-8 shrink-0"
              style={{
                backgroundColor: selectedSummaryModel === "gemini-2.5-pro" ? "var(--accent)" : "var(--grey-50)",
                color: selectedSummaryModel === "gemini-2.5-pro" ? "var(--on-accent)" : "var(--grey-600)",
              }}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>
                <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>
                <path d="M12 5v14"/>
                <path d="M12 12h6"/>
                <path d="M12 12H6"/>
              </svg>
            </div>
            <div className="flex-1 flex flex-col">
              <span className="font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
                Gemini 2.5 Pro (Rich Reasoning)
              </span>
              <span className="text-[var(--ink-secondary)] mt-0.5" style={{ fontSize: "var(--text-meta-size)" }}>
                Premium accuracy and deep reasoning for complex meeting topics.
              </span>
            </div>
            {selectedSummaryModel === "gemini-2.5-pro" && (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ color: "var(--accent)" }}
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </div>
        </div>

        {/* Claude 3.5 Sonnet */}
        <div
          onClick={() => setSelectedSummaryModel("claude-sonnet-4-5")}
          className="flex flex-col border rounded-[var(--radius-card)] p-[var(--space-3)] transition-all duration-[var(--dur-micro)] cursor-pointer hover:shadow-[var(--shadow-float)]"
          style={{
            backgroundColor: selectedSummaryModel === "claude-sonnet-4-5" ? "var(--accent-muted)" : "var(--canvas)",
            borderColor: selectedSummaryModel === "claude-sonnet-4-5" ? "var(--accent)" : "var(--grey-200)",
            borderWidth: selectedSummaryModel === "claude-sonnet-4-5" ? 2 : 1,
            padding: selectedSummaryModel === "claude-sonnet-4-5" ? "11px 11px" : "12px 12px",
          }}
        >
          <div className="flex items-center gap-[var(--space-3)]">
            <div
              className="flex items-center justify-center rounded-[var(--radius-control)] w-8 h-8 shrink-0"
              style={{
                backgroundColor: selectedSummaryModel === "claude-sonnet-4-5" ? "var(--accent)" : "var(--grey-50)",
                color: selectedSummaryModel === "claude-sonnet-4-5" ? "var(--on-accent)" : "var(--grey-600)",
              }}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 4l3 12h14l3-12-6 7-4-7-4 7-6-7z"/>
                <path d="M5 20h14a1 1 0 0 0 1-1v-1a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v1a1 1 0 0 0 1 1z"/>
              </svg>
            </div>
            <div className="flex-1 flex flex-col">
              <span className="font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
                Claude 3.5 Sonnet (Premium & Creative)
              </span>
              <span className="text-[var(--ink-secondary)] mt-0.5" style={{ fontSize: "var(--text-meta-size)" }}>
                High-end prose and creative text transformation.
              </span>
            </div>
            {selectedSummaryModel === "claude-sonnet-4-5" && (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ color: "var(--accent)" }}
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </div>
        </div>
      </div>

      {/* Verification / Success / Fail Message */}
      {present && (
        <div
          className="mt-[var(--space-6)] p-[var(--space-3)] rounded-[var(--radius-control)] bg-[var(--success-bg)] border border-[var(--success)] flex items-center gap-[var(--space-2)]"
          style={{ color: "var(--success-text)" }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <span className="font-medium" style={{ fontSize: "var(--text-body-size)" }}>
            Transcription engine ready
          </span>
        </div>
      )}

      {hasFailure && (
        <div
          className="mt-[var(--space-6)] p-[var(--space-3)] rounded-[var(--radius-control)] bg-[var(--error-bg)] border border-[var(--error)] flex items-start gap-[var(--space-2)]"
          style={{ color: "var(--error-text)" }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="mt-0.5 shrink-0"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <div className="flex flex-col gap-1">
            <span style={{ fontSize: "var(--text-body-size)" }}>
              Model download failed. Please check your internet connection and try again.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
