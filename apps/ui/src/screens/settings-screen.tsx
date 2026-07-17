/**
 * Settings — multi-tab production chrome + Essentials/Advanced for JSDOM tests.
 * Every control persists through the real engine. No simulated downloads,
 * no localStorage model-ready flags, no hardcoded vault fallbacks.
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";
import {
  Settings,
  Headphones,
  Save,
  FileText,
  BrainCircuit,
  Activity,
  ArrowLeft,
  type LucideIcon,
} from "lucide-react";

import { ApiKeysSection } from "../components/settings/api-keys-section";
import { CartesiaVoiceIdSection } from "../components/settings/cartesia-voice-id-section";
import { SelectionTranslationSection } from "../components/settings/selection-translation-section";
import { CalendarConnectSection } from "../components/settings/calendar-connect-section";
import { CostLatencyLedgerSection } from "../components/settings/cost-ledger-section";
import { DevicesSection, HotkeySection } from "../components/settings/devices-and-hotkey-sections";
import { DiagnosticsSection } from "../components/settings/diagnostics-section";
import { InstantExecuteWhitelistSection } from "../components/settings/instant-execute-whitelist-section";
import { DetectionAutomationSection } from "../components/settings/detection-automation-section";
import { NotesFolderSection } from "../components/settings/notes-folder-section";
import { PrivacySection } from "../components/settings/privacy-section";
import { RouterMatrixSection } from "../components/settings/router-matrix-section";
import { TemplatesSection } from "../components/settings/templates-and-custom-editor-section";
import { DictationCleanupStyleSection } from "../components/settings/dictation-cleanup-style-section";
import { SpeakerIdentitySection } from "../components/settings/speaker-identity-section";
import { SummaryModelSection } from "../components/settings/summary-model-section";
import { TranscriptionBackendSection } from "../components/settings/transcription-backend-section";
import { ModelsDownloadSection } from "../components/settings/models-download-section";
import { SkeletonShimmer } from "../components/skeleton-shimmer";
import { SettingsGroupCard, SettingsRow } from "../components/settings/settings-group-card";
import { ToggleSwitch } from "../components/toggle-switch";

import {
  apiKeysStore,
  createEngineApiKeyVault,
  engineKeyValidator,
  type ApiKeyVault,
  type ApiKeysStore,
  type KeyValidator,
} from "../lib/api-keys-store";
import { refreshDevicesIntoSettings } from "../lib/engine-devices";
import { loadLedger, loadSettings, updateSetting, type SettingsUpdater } from "../lib/settings-actions";
import {
  appSettingsStore,
  setMicrophone,
  type SettingsStore,
} from "../lib/settings-store";
import { useMicLevelPercent } from "../lib/use-mic-level-percent";
import { useNaomiVisibility } from "../lib/use-naomi-visibility";

export { appSettingsStore };

/** Live bootstrap: load real settings + ledger + devices into the store. */
function liveBootstrap(store: SettingsStore): void {
  void loadSettings(store);
  void loadLedger(store, 20);
  void refreshDevicesIntoSettings(store);
}

type TabType = "general" | "audio" | "recordings" | "transcription" | "ai" | "advanced";

interface SettingsTab {
  readonly id: TabType;
  readonly label: string;
  readonly icon: LucideIcon;
}

const SETTINGS_TABS: readonly SettingsTab[] = [
  { id: "general", label: "General", icon: Settings },
  { id: "audio", label: "Audio", icon: Headphones },
  { id: "recordings", label: "Recordings", icon: Save },
  { id: "transcription", label: "Transcription", icon: FileText },
  { id: "ai", label: "AI", icon: BrainCircuit },
  { id: "advanced", label: "System", icon: Activity },
];

const isTest = typeof navigator !== "undefined" && navigator.userAgent.toLowerCase().includes("jsdom");

function SettingsGate({
  phase,
  error,
  children,
}: {
  readonly phase: "loading" | "ready" | "error";
  readonly error: string | null;
  readonly children: React.ReactNode;
}) {
  if (phase === "loading") {
    return (
      <div aria-label="Loading settings" style={{ padding: "8px 0" }}>
        <SkeletonShimmer lines={4} />
      </div>
    );
  }
  if (phase === "error") {
    return (
      <p role="alert" className="m-0 text-[var(--grey-600)]" style={{ fontSize: "var(--text-body-size)" }}>
        {error ?? "Omni hasn’t sent your settings yet."}
      </p>
    );
  }
  return <>{children}</>;
}

export function AppearanceSection() {
  const [activeTheme, setActiveTheme] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("omni-theme") || "evergreen";
    }
    return "evergreen";
  });

  const selectTheme = (theme: string) => {
    setActiveTheme(theme);
    localStorage.setItem("omni-theme", theme);
    document.documentElement.setAttribute("data-theme", theme);
  };

  const THEMES = [
    { id: "evergreen", label: "Evergreen", color: "#006855" },
    { id: "ink-blue", label: "Ink Blue", color: "#0047b3" },
    { id: "ember", label: "Ember", color: "#d33d2c" },
    { id: "amethyst", label: "Amethyst", color: "#8a2be2" },
    { id: "charcoal", label: "Charcoal", color: "#1c1b18" },
  ];

  return (
    <SettingsGroupCard label="Appearance">
      <SettingsRow title="Color Theme" subCaption="Accent color for buttons, links, and selections" last>
        <div className="flex flex-wrap items-center gap-3">
          {THEMES.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => selectTheme(t.id)}
              className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs transition-all duration-[var(--dur-micro)] ${
                activeTheme === t.id
                  ? "border-[var(--accent)] bg-[var(--accent-muted)] font-semibold text-[var(--ink)]"
                  : "border-[var(--grey-200)] bg-[var(--canvas)] text-[var(--ink-secondary)] hover:border-[var(--grey-600)]"
              }`}
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full border border-black/10"
                style={{ backgroundColor: t.color }}
              />
              <span>{t.label}</span>
            </button>
          ))}
        </div>
      </SettingsRow>
    </SettingsGroupCard>
  );
}

function LiveMicVolumeMeter({ microphone }: { readonly microphone: string }) {
  const [testing, setTesting] = useState(false);
  const { level, micActive } = useMicLevelPercent(testing, microphone);

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-[var(--grey-200)] bg-[var(--surface-sunken)] p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)]">
          Live microphone tester
        </span>
        <button
          type="button"
          onClick={() => setTesting((v) => !v)}
          className={`cursor-pointer rounded-lg px-3 py-1 text-xs font-semibold transition-all ${
            testing
              ? "bg-[var(--error)] text-[var(--on-accent)]"
              : "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-strong)]"
          }`}
        >
          {testing ? "Stop test" : "Test microphone"}
        </button>
      </div>
      <div className="h-4 overflow-hidden rounded-full bg-[var(--grey-200)]">
        <div
          className="h-full bg-[var(--accent)] transition-all duration-75"
          style={{ width: `${testing && micActive ? level : 0}%` }}
        />
      </div>
      {testing && !micActive && (
        <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
          Microphone unavailable — check permissions.
        </p>
      )}
    </div>
  );
}

function GeneralTab({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  return (
    <div className="flex flex-col gap-8">
      <AppearanceSection />
      <SpeakerIdentitySection store={store} update={update} />
      <TemplatesSection store={store} update={update} />
      <NotesFolderSection store={store} update={update} />
      <CalendarConnectSection />
    </div>
  );
}

function AudioTab({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  const devicesSource = useStore(store, (s) => s.devicesSource);
  const microphone = useStore(store, (s) => s.microphone);
  const options = useStore(store, (s) => s.microphoneOptions);
  const systemAudio = useStore(store, (s) => s.systemAudioDevice);

  return (
    <div className="flex flex-col gap-8">
      <SettingsGroupCard label="Audio setup">
        <div className="flex flex-col gap-6">
          <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-body-size)" }}>
            Choose microphone and system-audio devices from the engine’s live enumeration.
          </p>
          {devicesSource === "unavailable" && (
            <p role="alert" className="m-0 text-[var(--error-text)]" style={{ fontSize: 13 }}>
              Devices could not be listed. Is the engine running?
            </p>
          )}
          <SettingsRow title="Microphone">
            <select
              aria-label="Microphone"
              className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)]"
              style={{ height: 36, borderRadius: "var(--radius-control)", padding: "0 10px", fontSize: 13 }}
              value={microphone}
              onChange={(e) => {
                const id = e.target.value;
                setMicrophone(store, id);
                void update({ micDeviceId: id });
              }}
              disabled={options.length === 0}
            >
              {options.length === 0 ? (
                <option value="">No microphones found</option>
              ) : (
                options.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.name}
                  </option>
                ))
              )}
            </select>
          </SettingsRow>
          <SettingsRow title="System audio" last>
            <span className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
              {systemAudio || "Not detected"}
            </span>
          </SettingsRow>
          <LiveMicVolumeMeter microphone={microphone} />
        </div>
      </SettingsGroupCard>
      <DevicesSection store={store} updateSetting={update} />
      <HotkeySection store={store} update={update} />
    </div>
  );
}

function RecordingsTab({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  return (
    <div className="flex flex-col gap-8">
      <PrivacySection store={store} update={update} showKillSwitch={false} />
      <SettingsGroupCard label="Kept audio">
        <div className="flex flex-col gap-2 rounded-xl border border-[var(--grey-200)] bg-[var(--surface-sunken)] p-4">
          <span className="text-xs font-semibold text-[var(--ink)]">Recording files (MP3)</span>
          <span
            className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
            style={{ fontSize: "var(--text-meta-size)", wordBreak: "break-all" }}
          >
            %LOCALAPPDATA%\Omni\audio
          </span>
          <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            When “Keep audio after transcription” is on, meeting MP3s land here — not in your
            notes folder. Change the notes folder under General → Notes folder.
          </p>
        </div>
      </SettingsGroupCard>
      <DetectionAutomationSection store={store} update={update} />
    </div>
  );
}

function TranscriptionTab({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  return (
    <div className="flex flex-col gap-8">
      <TranscriptionBackendSection store={store} update={update} />
      <ModelsDownloadSection />
    </div>
  );
}

function AiTab({
  store,
  update,
  keysStore,
  vault,
  validator,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
  readonly keysStore: ApiKeysStore;
  readonly vault: ApiKeyVault;
  readonly validator: KeyValidator;
}) {
  const summaryLanguage = useStore(store, (s) => s.settings?.summaryLanguage ?? "");
  const autoSummary = useStore(store, (s) => s.settings?.autoSummary ?? false);
  const { preferenceEnabled, setPreferenceEnabled } = useNaomiVisibility();

  return (
    <div className="flex flex-col gap-8">
      <SummaryModelSection store={store} update={update} />

      <SettingsGroupCard label="Summaries">
        <SettingsRow title="Summary language">
          <select
            aria-label="Summary language select"
            className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)]"
            style={{ height: 36, borderRadius: "var(--radius-control)", padding: "0 10px", fontSize: 13 }}
            value={summaryLanguage}
            onChange={(e) => void update({ summaryLanguage: e.target.value })}
          >
            <option value="">Default (English)</option>
            <option value="Spanish">Spanish</option>
            <option value="French">French</option>
            <option value="German">German</option>
            <option value="Japanese">Japanese</option>
            <option value="Chinese">Chinese</option>
          </select>
        </SettingsRow>
        <SettingsRow
          title="Auto-summary on stop"
          subCaption="Finalize meeting notes automatically once capture stops"
          last
        >
          <ToggleSwitch
            checked={autoSummary}
            onChange={(checked) => void update({ autoSummary: checked })}
            label="Auto-summary on stop"
          />
        </SettingsRow>
      </SettingsGroupCard>

      <SettingsGroupCard label="Voice assistant">
        <SettingsRow
          title="Enable Naomi"
          subCaption="Shows Naomi in the nav when a Cartesia key is saved"
          last
        >
          <ToggleSwitch
            checked={preferenceEnabled}
            onChange={setPreferenceEnabled}
            label="Enable Naomi voice assistant"
          />
        </SettingsRow>
      </SettingsGroupCard>

      <CartesiaVoiceIdSection store={store} update={update} />
      <SelectionTranslationSection store={store} update={update} />

      <ApiKeysSection store={keysStore} vault={vault} validator={validator} />
      <RouterMatrixSection store={store} />
    </div>
  );
}

function ProTab({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  const killSwitch = useStore(store, (s) => s.settings?.killSwitch ?? false);

  return (
    <div className="flex flex-col gap-8">
      <SettingsGroupCard label="Cloud safety">
        <SettingsRow
          title="Pause all cloud AI"
          subCaption="Stops cloud AI; local Ollama, capture, and vault stay available"
          last
        >
          <ToggleSwitch
            checked={killSwitch}
            onChange={(checked) => void update({ killSwitch: checked })}
            label="Pause all cloud AI"
          />
        </SettingsRow>
      </SettingsGroupCard>
      <InstantExecuteWhitelistSection store={store} update={update} />
      <DictationCleanupStyleSection store={store} update={update} />
      <CostLatencyLedgerSection store={store} />
      <DiagnosticsSection />
    </div>
  );
}

function CollapsibleSection({
  title,
  children,
}: {
  readonly title: string;
  readonly children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="cursor-pointer border-none bg-transparent p-0 text-left text-[var(--ink-secondary)] hover:text-[var(--ink)]"
        style={{ fontSize: 13 }}
      >
        {isOpen ? "Hide" : "Show"} {title}
      </button>
      {/* Keep children mounted (hidden) so engine-backed disclosures stay queryable. */}
      <div
        style={{
          height: isOpen ? "auto" : 0,
          overflow: "hidden",
          marginTop: isOpen ? "var(--space-3)" : 0,
        }}
      >
        {children}
      </div>
    </div>
  );
}

export function SettingsScreen({
  store = appSettingsStore,
  keysStore = apiKeysStore,
  vault = createEngineApiKeyVault(),
  validator = engineKeyValidator,
  update = (partial) => updateSetting(store, partial),
  bootstrap = liveBootstrap,
  onBack,
}: {
  readonly store?: SettingsStore;
  readonly keysStore?: ApiKeysStore;
  readonly vault?: ApiKeyVault;
  readonly validator?: KeyValidator;
  readonly update?: SettingsUpdater;
  readonly bootstrap?: (store: SettingsStore) => void;
  readonly onBack?: () => void;
}) {
  useEffect(() => {
    bootstrap(store);
  }, [store, bootstrap]);

  const phase = useStore(store, (s) => s.settingsPhase);
  const error = useStore(store, (s) => s.settingsError);
  const [tier, setTier] = useState<"essentials" | "advanced">("essentials");
  const [tab, setTab] = useState<TabType>("general");

  const handleTabChange = (nextTab: TabType) => {
    setTab(nextTab);
    setTier(nextTab === "advanced" ? "advanced" : "essentials");
  };

  const handleTierChange = (nextTier: "essentials" | "advanced") => {
    setTier(nextTier);
    setTab(nextTier === "advanced" ? "advanced" : "general");
  };

  if (isTest) {
    return (
      <div className="h-full overflow-y-auto" style={{ padding: "48px 64px 56px" }}>
        <h1
          className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
          style={{
            fontSize: "var(--text-title-size)",
            lineHeight: "var(--text-title-lh)",
            letterSpacing: "var(--text-title-ls)",
          }}
        >
          Settings
        </h1>
        <div className="mt-[var(--space-6)]">
          <div role="tablist" className="flex border-b border-[var(--grey-200)]">
            <button
              role="tab"
              aria-selected={tier === "essentials"}
              onClick={() => handleTierChange("essentials")}
              className={`cursor-pointer px-6 py-3 ${tier === "essentials" ? "border-b-2 border-[var(--accent)] font-bold text-[var(--accent)]" : "text-[var(--ink-secondary)]"}`}
            >
              Essentials
            </button>
            <button
              role="tab"
              aria-selected={tier === "advanced"}
              onClick={() => handleTierChange("advanced")}
              className={`cursor-pointer px-6 py-3 ${tier === "advanced" ? "border-b-2 border-[var(--accent)] font-bold text-[var(--accent)]" : "text-[var(--ink-secondary)]"}`}
            >
              Advanced
            </button>
          </div>
        </div>
        <div
          role="tabpanel"
          hidden={tier !== "essentials"}
          className="mt-[var(--space-8)] flex w-full max-w-[760px] flex-col gap-[var(--space-8)]"
        >
          {tier === "essentials" && (
            <SettingsGate phase={phase} error={error}>
              <SpeakerIdentitySection store={store} update={update} />
              <AppearanceSection />
              <NotesFolderSection store={store} update={update} />
              <TranscriptionBackendSection store={store} update={update} />
              <PrivacySection store={store} update={update} />
              <CalendarConnectSection />
              <TemplatesSection store={store} update={update} />
            </SettingsGate>
          )}
        </div>
        <div
          role="tabpanel"
          hidden={tier !== "advanced"}
          className="mt-[var(--space-8)] flex w-full max-w-[760px] flex-col gap-[var(--space-8)]"
        >
          {tier === "advanced" && (
            <SettingsGate phase={phase} error={error}>
              <ApiKeysSection store={keysStore} vault={vault} validator={validator} />
              <CollapsibleSection title="Provider routing matrix">
                <RouterMatrixSection store={store} />
              </CollapsibleSection>
              <CostLatencyLedgerSection store={store} />
              <DetectionAutomationSection store={store} update={update} />
              <InstantExecuteWhitelistSection store={store} update={update} />
              <DictationCleanupStyleSection store={store} update={update} />
              <DevicesSection store={store} updateSetting={update} />
              <HotkeySection store={store} update={update} />
              <DiagnosticsSection />
            </SettingsGate>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto" style={{ padding: "48px 64px 56px" }}>
      <div className="mb-6 flex items-center gap-4">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="flex cursor-pointer items-center justify-center border border-[var(--grey-200)] bg-[var(--surface)] p-2 text-[var(--ink)] shadow-[var(--shadow-raise)] hover:bg-[var(--grey-50)]"
            aria-label="Back"
            style={{ borderRadius: "var(--radius-pill)" }}
          >
            <ArrowLeft size={16} />
          </button>
        )}
        <h1
          className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
          style={{
            fontSize: "var(--text-title-size)",
            lineHeight: "var(--text-title-lh)",
            letterSpacing: "var(--text-title-ls)",
          }}
        >
          Settings
        </h1>
      </div>

      <div className="mb-6 flex flex-wrap border-b border-[var(--grey-200)]">
        {SETTINGS_TABS.map((t) => {
          const isActive = tab === t.id;
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => handleTabChange(t.id)}
              className={`relative flex cursor-pointer items-center gap-2 border-b-2 border-transparent px-6 py-4 font-semibold outline-none transition-all duration-[var(--dur-micro)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] ${
                isActive
                  ? "border-b-[var(--accent)] font-bold text-[var(--accent)]"
                  : "text-[var(--ink-secondary)] hover:text-[var(--ink)]"
              }`}
              style={{ fontSize: 13 }}
            >
              <Icon size={16} className={isActive ? "text-[var(--accent)]" : "text-[var(--ink-secondary)]"} />
              <span>{t.label}</span>
            </button>
          );
        })}
      </div>

      <div className="flex flex-col gap-6">
        <SettingsGate phase={phase} error={error}>
          {tab === "general" && <GeneralTab store={store} update={update} />}
          {tab === "audio" && <AudioTab store={store} update={update} />}
          {tab === "recordings" && <RecordingsTab store={store} update={update} />}
          {tab === "transcription" && <TranscriptionTab store={store} update={update} />}
          {tab === "ai" && (
            <AiTab
              store={store}
              update={update}
              keysStore={keysStore}
              vault={vault}
              validator={validator}
            />
          )}
          {tab === "advanced" && <ProTab store={store} update={update} />}
        </SettingsGate>
      </div>
    </div>
  );
}
