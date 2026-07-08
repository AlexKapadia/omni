/**
 * First-run wizard (design §09): five 560×560 cards centred on the canvas.
 * Steps: welcome → vault → keys → models → Google Calendar → finish.
 */
import { useEffect, useMemo } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../../components/button";
import { OnboardingCardFrame } from "../../components/onboarding/onboarding-card-frame";
import { StepGoogleCalendar } from "../../components/onboarding/step-google-calendar";
import { StepKeys } from "../../components/onboarding/step-keys";
import { StepModels } from "../../components/onboarding/step-models";
import { StepVault } from "../../components/onboarding/step-vault";
import { StepWelcome } from "../../components/onboarding/step-welcome";
import {
  apiKeysStore,
  createEngineApiKeyVault,
  engineKeyValidator,
  KEY_PROVIDER_LABELS,
  type ApiKeyVault,
  type ApiKeysStore,
  type KeyValidator,
} from "../../lib/api-keys-store";
import { REQUIRED_KEY_PROVIDERS } from "../../lib/setup-settings-commands";
import {
  createOnboardingFlowStore,
  goToStep,
  modelsPresent,
  type OnboardingFlowStore,
  type OnboardingStep,
} from "../../lib/onboarding-flow-store";
import {
  beginGoogleConnect,
  beginModelDownload,
  chooseVaultFolder,
  configureVault,
  finishOnboarding,
  initFromSetupStatus,
  skipGoogleConnect,
  subscribeGoogleConnect,
  subscribeModelDownload,
} from "../../lib/onboarding-flow-actions";
import { connectGoogle } from "../../lib/setup-settings-repository";
import type { SetupStatus } from "../../lib/setup-settings-payloads";

/** Injectable action seam — real engine actions by default, fakes in tests. */
export interface OnboardingActions {
  initFromSetupStatus: (store: OnboardingFlowStore) => Promise<void>;
  chooseVaultFolder: (store: OnboardingFlowStore) => Promise<void>;
  configureVault: (store: OnboardingFlowStore, path: string, createNew: boolean) => Promise<boolean>;
  subscribeModelDownload: (store: OnboardingFlowStore) => () => void;
  beginModelDownload: (store: OnboardingFlowStore) => Promise<void>;
  subscribeGoogleConnect: (store: OnboardingFlowStore) => () => void;
  beginGoogleConnect: (
    store: OnboardingFlowStore,
    credentials?: { readonly clientId: string; readonly clientSecret: string },
  ) => Promise<void>;
  skipGoogleConnect: (store: OnboardingFlowStore) => void;
  finishOnboarding: (
    store: OnboardingFlowStore,
    onDone: (status: SetupStatus) => void,
  ) => Promise<void>;
}

const LIVE_ACTIONS: OnboardingActions = {
  initFromSetupStatus: (store) => initFromSetupStatus(store),
  chooseVaultFolder: (store) => chooseVaultFolder(store),
  configureVault: (store, path, createNew) => configureVault(store, path, createNew),
  subscribeModelDownload: (store) => subscribeModelDownload(store),
  beginModelDownload: (store) => beginModelDownload(store),
  subscribeGoogleConnect: (store) => subscribeGoogleConnect(store),
  beginGoogleConnect: (store, credentials) => beginGoogleConnect(store, connectGoogle, credentials),
  skipGoogleConnect: (store) => skipGoogleConnect(store),
  finishOnboarding: (store, onDone) => finishOnboarding(store, onDone),
};

export function OnboardingWizard({
  onComplete,
  flowStore: flowStoreProp,
  keysStore = apiKeysStore,
  vault: vaultProp,
  validator = engineKeyValidator,
  actions = LIVE_ACTIONS,
}: {
  readonly onComplete: (status: SetupStatus) => void;
  readonly flowStore?: OnboardingFlowStore;
  readonly keysStore?: ApiKeysStore;
  readonly vault?: ApiKeyVault;
  readonly validator?: KeyValidator;
  readonly actions?: OnboardingActions;
}) {
  const flowStore = useMemo(
    () => flowStoreProp ?? createOnboardingFlowStore(),
    [flowStoreProp],
  );
  const vault = useMemo(() => vaultProp ?? createEngineApiKeyVault(), [vaultProp]);

  const step = useStore(flowStore, (s) => s.step);
  const vaultConfigured = useStore(flowStore, (s) => s.vaultConfigured);
  const present = useStore(flowStore, modelsPresent);
  const requiredKeysValid = useStore(keysStore, (s) =>
    REQUIRED_KEY_PROVIDERS.every((p) => s.validation[p].status === "valid"),
  );

  useEffect(() => {
    void actions.initFromSetupStatus(flowStore);
    const unsubModels = actions.subscribeModelDownload(flowStore);
    const unsubGoogle = actions.subscribeGoogleConnect(flowStore);
    return () => {
      unsubModels();
      unsubGoogle();
    };
  }, [flowStore, actions]);

  const canFinish = requiredKeysValid && vaultConfigured && present;
  const finishBlockedReason = canFinish ? null : buildBlockedReason(requiredKeysValid, vaultConfigured, present);

  const advance = (to: OnboardingStep) => goToStep(flowStore, to);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-[var(--space-4)] bg-[var(--canvas)]">
      <OnboardingCardFrame step={step}>
        {step === 1 && <StepWelcome onBegin={() => advance(2)} />}
        {step === 2 && (
          <StepVault
            store={flowStore}
            onBrowse={() => void actions.chooseVaultFolder(flowStore)}
            onUseFolder={(path, createNew) => void actions.configureVault(flowStore, path, createNew)}
          />
        )}
        {step === 3 && <StepKeys store={keysStore} vault={vault} validator={validator} />}
        {step === 4 && (
          <StepModels store={flowStore} onDownload={() => void actions.beginModelDownload(flowStore)} />
        )}
        {step === 5 && (
          <StepGoogleCalendar
            store={flowStore}
            canFinish={canFinish}
            finishBlockedReason={finishBlockedReason}
            onConnectGoogle={(credentials) => void actions.beginGoogleConnect(flowStore, credentials)}
            onSkipGoogle={() => actions.skipGoogleConnect(flowStore)}
            onFinish={() => void actions.finishOnboarding(flowStore, onComplete)}
          />
        )}
      </OnboardingCardFrame>

      {step > 1 && step < 5 && (
        <div className="flex items-center gap-[var(--space-4)]" style={{ width: 560 }}>
          <OmniButton variant="ghost" onClick={() => advance((step - 1) as OnboardingStep)}>
            Back
          </OmniButton>
          <OmniButton
            variant="secondary"
            className="ml-auto"
            disabled={(step === 2 && !vaultConfigured) || (step === 4 && !present)}
            onClick={() => advance((step + 1) as OnboardingStep)}
          >
            Continue
          </OmniButton>
        </div>
      )}
      {step === 5 && (
        <div className="flex items-center gap-[var(--space-4)]" style={{ width: 560 }}>
          <OmniButton variant="ghost" onClick={() => advance(4)}>
            Back
          </OmniButton>
        </div>
      )}
    </div>
  );
}

function buildBlockedReason(keysValid: boolean, vaultSet: boolean, models: boolean): string {
  const missing: string[] = [];
  if (!keysValid) {
    missing.push(`validate your ${REQUIRED_KEY_PROVIDERS.map((p) => KEY_PROVIDER_LABELS[p]).join(" and ")} keys`);
  }
  if (!vaultSet) missing.push("set your vault");
  if (!models) missing.push("download the models");
  return `To finish, ${missing.join(", ")}.`;
}
