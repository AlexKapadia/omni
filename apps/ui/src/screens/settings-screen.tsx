/**
 * Settings — two-column shell (components doc §10) composing the group cards:
 * Devices, Hotkey, Templates, Privacy, Instant execute | AI router,
 * Cost + latency, API keys.
 *
 * Everything is REAL engine data: on mount the screen loads settings.get and
 * ledger.summary and enumerates real devices; every control persists through
 * settings.update. There is no mock data. The settings-backed cards show an
 * honest loading shimmer / error until settings.get resolves.
 */
import { useEffect } from "react";
import { useStore } from "zustand";
import { ApiKeysSection } from "../components/settings/api-keys-section";
import { CostLatencyLedgerSection } from "../components/settings/cost-ledger-section";
import { DevicesSection, HotkeySection } from "../components/settings/devices-and-hotkey-sections";
import { InstantExecuteWhitelistSection } from "../components/settings/instant-execute-whitelist-section";
import { DetectionAutomationSection } from "../components/settings/detection-automation-section";
import { PrivacySection } from "../components/settings/privacy-section";
import { RouterMatrixSection } from "../components/settings/router-matrix-section";
import { TemplatesSection } from "../components/settings/templates-and-custom-editor-section";
import { SkeletonShimmer } from "../components/skeleton-shimmer";
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
import { createSettingsStore, type SettingsStore } from "../lib/settings-store";

/** The one settings store the running app uses (filled from the real engine). */
export const appSettingsStore: SettingsStore = createSettingsStore();

/** Live bootstrap: load real settings + ledger + devices into the store. */
function liveBootstrap(store: SettingsStore): void {
  void loadSettings(store);
  void loadLedger(store, 20);
  void refreshDevicesIntoSettings(store);
}

export function SettingsScreen({
  store = appSettingsStore,
  keysStore = apiKeysStore,
  vault = createEngineApiKeyVault(),
  validator = engineKeyValidator,
  update = (partial) => updateSetting(store, partial),
  bootstrap = liveBootstrap,
}: {
  readonly store?: SettingsStore;
  readonly keysStore?: ApiKeysStore;
  readonly vault?: ApiKeyVault;
  readonly validator?: KeyValidator;
  readonly update?: SettingsUpdater;
  /** Injectable for tests; the default asks the engine for everything real. */
  readonly bootstrap?: (store: SettingsStore) => void;
}) {
  useEffect(() => {
    bootstrap(store);
  }, [store, bootstrap]);

  const phase = useStore(store, (s) => s.settingsPhase);
  const error = useStore(store, (s) => s.settingsError);

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
      <div
        className="mt-[var(--space-8)] grid grid-cols-1 items-start lg:grid-cols-2"
        style={{ gap: "var(--space-12)" }}
      >
        <div className="flex min-w-0 flex-col gap-[var(--space-8)]">
          <DevicesSection store={store} />
          {phase === "loading" ? (
            <div aria-label="Loading settings" style={{ padding: "8px 0" }}>
              <SkeletonShimmer lines={3} />
            </div>
          ) : phase === "error" ? (
            <p
              role="alert"
              className="m-0 text-[var(--grey-600)]"
              style={{ fontSize: "var(--text-body-size)" }}
            >
              {error ?? "The engine did not send your settings."}
            </p>
          ) : (
            <>
              <HotkeySection store={store} update={update} />
              <DetectionAutomationSection store={store} update={update} />
              <TemplatesSection store={store} update={update} />
              <PrivacySection store={store} update={update} />
              <InstantExecuteWhitelistSection store={store} update={update} />
            </>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-[var(--space-8)]">
          <RouterMatrixSection store={store} />
          <CostLatencyLedgerSection store={store} />
          <ApiKeysSection store={keysStore} vault={vault} validator={validator} />
        </div>
      </div>
    </div>
  );
}
