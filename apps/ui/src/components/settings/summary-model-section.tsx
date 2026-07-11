/**
 * Meetily-style summary model settings: pick a provider, pick (or pull) a
 * model, and point at a local Ollama endpoint. Ollama/built-in AI models can
 * be listed and pulled on-device; cloud providers just need a saved key
 * (see ApiKeysSection). Parsing + wire helpers live in lib/ollama-commands.ts
 * and lib/setup-settings-repository.ts to keep this file focused.
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";

import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { updateSetting, type SettingsUpdater } from "../../lib/settings-actions";
import { listOllamaModels, pingOllama, pullOllamaModel } from "../../lib/setup-settings-repository";
import { subscribeToOllamaPull } from "../../lib/setup-settings-transport";
import { DEFAULT_OLLAMA_MODEL_ID, OLLAMA_MODEL_OPTIONS, type OllamaModel } from "../../lib/ollama-commands";
import type { SettingsStore } from "../../lib/settings-store";
import type { SummaryProvider } from "../../lib/setup-settings-commands";

type CloudProvider = "gemini" | "anthropic" | "openai";

const CLOUD_MODEL_OPTIONS: Readonly<Record<CloudProvider, readonly { readonly id: string; readonly label: string }[]>> = {
  gemini: [
    { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
  ],
  anthropic: [{ id: "claude-sonnet-4-5", label: "Claude Sonnet" }],
  openai: [{ id: "gpt-4o", label: "OpenAI GPT-4o" }],
};

const PROVIDER_OPTIONS: readonly { readonly id: SummaryProvider; readonly label: string }[] = [
  { id: "ollama", label: "Ollama (local)" },
  { id: "builtin-ai", label: "Built-in AI (local)" },
  { id: "gemini", label: "Gemini (needs key)" },
  { id: "anthropic", label: "Claude (needs key)" },
  { id: "openai", label: "OpenAI (needs key)" },
];

function isCloudProvider(provider: SummaryProvider): provider is CloudProvider {
  return provider === "gemini" || provider === "anthropic" || provider === "openai";
}

function defaultModelFor(provider: SummaryProvider): string {
  return isCloudProvider(provider) ? CLOUD_MODEL_OPTIONS[provider][0]!.id : DEFAULT_OLLAMA_MODEL_ID;
}

const SELECT_CLASS =
  "cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]";
const SELECT_STYLE = {
  height: "var(--control-height-sm)",
  borderRadius: "var(--radius-control)",
  padding: "0 var(--space-2)",
  fontSize: 13,
} as const;

export function SummaryModelSection({
  store,
  update = (partial) => updateSetting(store, partial),
}: {
  readonly store: SettingsStore;
  readonly update?: SettingsUpdater;
}) {
  const provider = useStore(store, (s) => s.settings?.summaryProvider ?? "ollama");
  const modelId = useStore(store, (s) => s.settings?.summaryModelId ?? DEFAULT_OLLAMA_MODEL_ID);
  const ollamaBaseUrl = useStore(store, (s) => s.settings?.ollamaBaseUrl ?? "http://127.0.0.1:11434");
  const isLocal = provider === "ollama" || provider === "builtin-ai";

  const [localModels, setLocalModels] = useState<readonly OllamaModel[]>([]);
  const [listBusy, setListBusy] = useState(false);
  const [pullBusy, setPullBusy] = useState(false);
  const [pullProgress, setPullProgress] = useState<{ received: number; total: number | null } | null>(null);
  const [testBusy, setTestBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Local draft so partial URLs (e.g. "http://127.0.0.1:1") do not round-trip
  // through settings.update and get rejected/reverted mid-keystroke.
  const [ollamaUrlDraft, setOllamaUrlDraft] = useState(ollamaBaseUrl);

  useEffect(() => {
    setOllamaUrlDraft(ollamaBaseUrl);
  }, [ollamaBaseUrl]);

  const persistOllamaUrl = (raw: string): void => {
    const trimmed = raw.trim();
    if (trimmed === ollamaBaseUrl) return;
    if (trimmed && !trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
      setOllamaUrlDraft(ollamaBaseUrl);
      return;
    }
    void update({ ollamaBaseUrl: trimmed });
  };

  useEffect(() => {
    return subscribeToOllamaPull({
      onProgress: (p) => setPullProgress({ received: p.receivedBytes, total: p.totalBytes }),
      onFailed: (f) => {
        setPullBusy(false);
        setPullProgress(null);
        setErrorMessage(f.message || `Could not pull ${f.model}.`);
      },
      onCompleted: (c) => {
        setPullBusy(false);
        setPullProgress(null);
        setErrorMessage(null);
        setStatusMessage(`Pulled ${c.model}.`);
        void refreshModels();
      },
    });
    // Runs once: the subscription lives for the component's lifetime and
    // reads the current base URL fresh on each button click, not here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshModels = async (): Promise<void> => {
    setListBusy(true);
    setErrorMessage(null);
    try {
      setLocalModels(await listOllamaModels());
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Could not list local models.");
    } finally {
      setListBusy(false);
    }
  };

  const testConnection = async (): Promise<void> => {
    setTestBusy(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const result = await pingOllama();
      if (result.ok) {
        setStatusMessage(result.version ? `Connected (Ollama ${result.version}).` : "Connected.");
      } else {
        setErrorMessage(result.error || "Could not connect to Ollama.");
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Could not reach Ollama.");
    } finally {
      setTestBusy(false);
    }
  };

  const pullSelected = async (): Promise<void> => {
    setPullBusy(true);
    setPullProgress(null);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      await pullOllamaModel(modelId);
    } catch (err) {
      setPullBusy(false);
      setErrorMessage(err instanceof Error ? err.message : "Could not start the pull.");
    }
  };

  const selectProvider = (next: SummaryProvider): void => {
    void update({ summaryProvider: next, summaryModelId: defaultModelFor(next) });
  };

  const modelOptions: readonly { readonly id: string; readonly label: string }[] = isCloudProvider(provider)
    ? CLOUD_MODEL_OPTIONS[provider]
    : [
        ...OLLAMA_MODEL_OPTIONS,
        ...localModels
          .filter((m) => !OLLAMA_MODEL_OPTIONS.some((o) => o.id === m.name))
          .map((m) => ({ id: m.name, label: m.name })),
      ];

  const pct =
    pullProgress?.total !== null && pullProgress?.total !== undefined && pullProgress.total > 0
      ? Math.min(100, Math.round((pullProgress.received / pullProgress.total) * 100))
      : null;

  return (
    <SettingsGroupCard label="Summary AI model">
      <SettingsRow
        title="Provider"
        subCaption="Ollama-first (Meetily-style); cloud providers need a saved API key."
      >
        <select
          aria-label="Summary provider"
          className={SELECT_CLASS}
          style={SELECT_STYLE}
          value={provider}
          onChange={(e) => selectProvider(e.target.value as SummaryProvider)}
        >
          {PROVIDER_OPTIONS.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </SettingsRow>

      <SettingsRow title="Model" last={!isLocal}>
        <select
          aria-label="Summary model"
          className={SELECT_CLASS}
          style={SELECT_STYLE}
          value={modelId}
          onChange={(e) => void update({ summaryModelId: e.target.value })}
        >
          {modelOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </SettingsRow>

      {isLocal && (
        <>
          <SettingsRow title="Ollama endpoint" subCaption="Leave default for local Ollama" last>
            <input
              aria-label="Ollama endpoint"
              className="omni-input w-full"
              style={{ height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8, fontSize: 13 }}
              value={ollamaUrlDraft}
              placeholder="http://127.0.0.1:11434"
              onChange={(e) => setOllamaUrlDraft(e.target.value)}
              onBlur={() => persistOllamaUrl(ollamaUrlDraft)}
            />
          </SettingsRow>

          <div className="flex flex-col gap-2 pb-3 pt-1">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={listBusy}
                onClick={() => void refreshModels()}
                className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] px-2 py-1 disabled:opacity-60"
                style={{ borderRadius: "var(--radius-control)", fontSize: 12 }}
              >
                {listBusy ? "Listing…" : "List models"}
              </button>
              <button
                type="button"
                disabled={pullBusy}
                onClick={() => void pullSelected()}
                className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] px-2 py-1 disabled:opacity-60"
                style={{ borderRadius: "var(--radius-control)", fontSize: 12 }}
              >
                {pullBusy ? "Pulling…" : "Pull selected"}
              </button>
              <button
                type="button"
                disabled={testBusy}
                onClick={() => void testConnection()}
                className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] px-2 py-1 disabled:opacity-60"
                style={{ borderRadius: "var(--radius-control)", fontSize: 12 }}
              >
                {testBusy ? "Testing…" : "Test connection"}
              </button>
            </div>

            {pullBusy && (
              <div className="h-1.5 w-40 overflow-hidden rounded-full bg-[var(--grey-200)]">
                <div
                  className="h-full bg-[var(--accent)] transition-all duration-300"
                  style={{ width: pct !== null ? `${pct}%` : "30%" }}
                />
              </div>
            )}
            {statusMessage && (
              <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
                {statusMessage}
              </p>
            )}
            {errorMessage && (
              <p role="alert" className="m-0 text-[var(--error-text)]" style={{ fontSize: 12 }}>
                {errorMessage}
              </p>
            )}
          </div>
        </>
      )}
    </SettingsGroupCard>
  );
}
