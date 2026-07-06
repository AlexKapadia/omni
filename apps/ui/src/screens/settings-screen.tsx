/**
 * Settings — two-column shell (components doc §10) composing the group
 * cards: Devices, Hotkey, Templates | AI router, Cost + latency, Privacy,
 * API keys. Owns the app-singleton settings store (mock initial data behind
 * real shapes) and the mock API-key vault; both swap for engine-backed
 * implementations without touching this screen.
 */
import { ApiKeysSection } from "../components/settings/api-keys-section";
import {
  DevicesSection,
  HotkeySection,
  TemplatesSection,
} from "../components/settings/devices-hotkey-templates-sections";
import { PrivacySection } from "../components/settings/privacy-section";
import {
  CostLatencyLedgerSection,
  RouterMatrixSection,
} from "../components/settings/router-and-ledger-sections";
import {
  apiKeysStore,
  createMockApiKeyVault,
  type ApiKeysStore,
  type ApiKeyVault,
} from "../lib/api-keys-store";
import { buildMockInitialSettings } from "../lib/mock-settings-data";
import { createSettingsStore, type SettingsStore } from "../lib/settings-store";

/** The one settings store the running app uses (MOCK initial data). */
export const appSettingsStore: SettingsStore = createSettingsStore(buildMockInitialSettings());

/** MOCK vault until the engine's DPAPI endpoint lands (same interface). */
const defaultVault: ApiKeyVault = createMockApiKeyVault();

export function SettingsScreen({
  store = appSettingsStore,
  keysStore = apiKeysStore,
  vault = defaultVault,
}: {
  readonly store?: SettingsStore;
  readonly keysStore?: ApiKeysStore;
  readonly vault?: ApiKeyVault;
}) {
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
          <HotkeySection store={store} />
          <TemplatesSection store={store} />
          <PrivacySection store={store} />
        </div>
        <div className="flex min-w-0 flex-col gap-[var(--space-8)]">
          <RouterMatrixSection store={store} />
          <CostLatencyLedgerSection store={store} />
          <ApiKeysSection store={keysStore} vault={vault} />
        </div>
      </div>
    </div>
  );
}
