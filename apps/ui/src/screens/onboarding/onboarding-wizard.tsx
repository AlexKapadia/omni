import { useEffect, useMemo, useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../../components/button";
import { OnboardingCardFrame } from "../../components/onboarding/onboarding-card-frame";
import { StepWelcome } from "../../components/onboarding/step-welcome";
import { StepFeaturesTour } from "../../components/onboarding/step-features-tour";
import { StepSpeakerIdentity } from "../../components/onboarding/step-speaker-identity";
import { StepVault, DEFAULT_VAULT_PATH } from "../../components/onboarding/step-vault";
import { StepKeys } from "../../components/onboarding/step-keys";
import { StepModels } from "../../components/onboarding/step-models";
import {
  apiKeysStore,
  createEngineApiKeyVault,
  engineKeyValidator,
  type ApiKeyVault,
  type ApiKeysStore,
  type KeyValidator,
} from "../../lib/api-keys-store";
import {
  createOnboardingFlowStore,
  goToStep,
  modelsPresent,
  applyModelFailed,
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
import { enrollSpeaker } from "../../lib/speaker-enroll-repository";
import { updateSettings } from "../../lib/setup-settings-repository";
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
  enrollSpeaker: (name: string) => Promise<void>;
  saveEngineSelection: (
    engine: "parakeet" | "whisper",
    summaryModelId: string,
  ) => Promise<void>;
}

const LIVE_ACTIONS: OnboardingActions = {
  initFromSetupStatus: (store) => initFromSetupStatus(store),
  chooseVaultFolder: (store) => chooseVaultFolder(store),
  configureVault: (store, path, createNew) => configureVault(store, path, createNew),
  subscribeModelDownload: (store) => subscribeModelDownload(store),
  beginModelDownload: (store) => beginModelDownload(store),
  subscribeGoogleConnect: (store) => subscribeGoogleConnect(store),
  beginGoogleConnect: (store, credentials) => beginGoogleConnect(store, undefined, credentials),
  skipGoogleConnect: (store) => skipGoogleConnect(store),
  finishOnboarding: (store, onDone) => finishOnboarding(store, onDone),
  enrollSpeaker: (name) => enrollSpeaker(name).then(() => undefined),
  saveEngineSelection: (engine, summaryModelId) =>
    updateSettings(
      {
        sttEngine: engine,
        sttModelId: engine === "whisper" ? "large-v3" : "",
        summaryModelId,
      },
      null,
    ),
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
  const vaultPath = useStore(flowStore, (s) => s.vaultPath);
  const vaultBusy = useStore(flowStore, (s) => s.vaultBusy);

  const modelsReady = useStore(flowStore, modelsPresent);
  const modelsStarted = useStore(flowStore, (s) => s.modelsStarted);

  const finishing = useStore(flowStore, (s) => s.finishing);
  const finishError = useStore(flowStore, (s) => s.finishError);

  // Speaker name state (Step 3)
  const [speakerName, setSpeakerName] = useState("");
  const [speakerBusy, setSpeakerBusy] = useState(false);
  const [speakerError, setSpeakerError] = useState<string | null>(null);

  // Vault configuration inputs state (Step 4)
  const [vaultPathInput, setVaultPathInput] = useState(vaultPath ?? DEFAULT_VAULT_PATH);
  const [createNewInput, setCreateNewInput] = useState(vaultPath === null);

  // Model selection state (Step 5)
  const [selectedEngine, setSelectedEngine] = useState<"parakeet" | "whisper">("parakeet");
  const [selectedSummaryModel, setSelectedSummaryModel] = useState<string>("gemini-2.5-flash");

  // Mirror picked vault path from store to local input state
  useEffect(() => {
    if (vaultPath !== null) {
      setVaultPathInput(vaultPath);
      setCreateNewInput(false);
    }
  }, [vaultPath]);

  useEffect(() => {
    void actions.initFromSetupStatus(flowStore);
    const unsubModels = actions.subscribeModelDownload(flowStore);
    const unsubGoogle = actions.subscribeGoogleConnect(flowStore);
    return () => {
      unsubModels();
      unsubGoogle();
    };
  }, [flowStore, actions]);

  const advance = (to: OnboardingStep) => goToStep(flowStore, to);

  const footer = (
    <div className="flex items-center justify-between w-full">
      {/* Left-aligned Back button */}
      <OmniButton
        variant="ghost"
        onClick={() => advance((step - 1) as OnboardingStep)}
        disabled={speakerBusy || vaultBusy || finishing}
      >
        Back
      </OmniButton>

      {/* Right-aligned action buttons */}
      <div className="flex items-center gap-[var(--space-3)]">
        {step === 2 && (
          <OmniButton
            variant="primary"
            onClick={() => advance(3)}
          >
            Got it, continue
          </OmniButton>
        )}

        {step === 3 && (
          <>
            <OmniButton
              variant="ghost"
              onClick={() => advance(4)}
              disabled={speakerBusy}
            >
              Skip
            </OmniButton>
            <OmniButton
              variant="primary"
              disabled={speakerBusy || speakerName.trim().length === 0}
              loading={speakerBusy}
              onClick={async () => {
                setSpeakerBusy(true);
                setSpeakerError(null);
                try {
                  await actions.enrollSpeaker(speakerName.trim());
                  advance(4);
                } catch (err) {
                  setSpeakerError(err instanceof Error ? err.message : "Could not save your name.");
                } finally {
                  setSpeakerBusy(false);
                }
              }}
            >
              Continue
            </OmniButton>
          </>
        )}

        {step === 4 && (
          <OmniButton
            variant="primary"
            disabled={vaultBusy || vaultPathInput.trim().length === 0}
            loading={vaultBusy}
            onClick={async () => {
              const ok = await actions.configureVault(flowStore, vaultPathInput, createNewInput);
              if (ok) {
                advance(5);
              }
            }}
          >
            Continue
          </OmniButton>
        )}

        {step === 5 && (
          <>
            {!modelsReady && !modelsStarted && (
              <OmniButton
                variant="primary"
                onClick={async () => {
                  try {
                    await actions.saveEngineSelection(selectedEngine, selectedSummaryModel);
                    void actions.beginModelDownload(flowStore);
                  } catch (err) {
                    applyModelFailed(flowStore, "download", err instanceof Error ? err.message : "Failed to select model.");
                  }
                }}
              >
                Download & continue
              </OmniButton>
            )}
            {modelsStarted && (
              <OmniButton
                variant="primary"
                disabled
                loading
              >
                Downloading…
              </OmniButton>
            )}
            {modelsReady && (
              <OmniButton
                variant="primary"
                onClick={() => advance(6)}
              >
                Continue
              </OmniButton>
            )}
          </>
        )}

        {step === 6 && (
          <OmniButton
            variant="primary"
            disabled={finishing}
            loading={finishing}
            onClick={() => void actions.finishOnboarding(flowStore, onComplete)}
          >
            Finish
          </OmniButton>
        )}
      </div>
    </div>
  );

  return (
    <div className="flex h-full flex-col items-center justify-center gap-[var(--space-4)] bg-[var(--canvas)] p-[var(--space-4)]">
      <OnboardingCardFrame step={step} footer={step > 1 ? footer : undefined}>
        {step === 1 && <StepWelcome onBegin={() => advance(2)} />}
        
        {step === 2 && <StepFeaturesTour onContinue={() => advance(3)} />}

        {step === 3 && (
          <div className="flex flex-col h-full justify-between">
            <div>
              <StepSpeakerIdentity
                name={speakerName}
                onChangeName={setSpeakerName}
              />
              {speakerError && (
                <div 
                  className="mt-[var(--space-4)] p-[var(--space-3)] rounded-[var(--radius-control)] bg-[var(--error-bg)] border border-[var(--error)] flex items-start gap-[var(--space-2)]"
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
                  <span style={{ fontSize: "var(--text-body-size)" }}>
                    {speakerError}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {step === 4 && (
          <StepVault
            store={flowStore}
            path={vaultPathInput}
            setPath={setVaultPathInput}
            createNew={createNewInput}
            setCreateNew={setCreateNewInput}
            onBrowse={() => void actions.chooseVaultFolder(flowStore)}
          />
        )}

        {step === 5 && (
          <StepModels
            store={flowStore}
            selectedEngine={selectedEngine}
            setSelectedEngine={setSelectedEngine}
            selectedSummaryModel={selectedSummaryModel}
            setSelectedSummaryModel={setSelectedSummaryModel}
          />
        )}

        {step === 6 && (
          <div className="flex flex-col justify-between h-full">
            <div>
              <StepKeys
                store={keysStore}
                vault={vault}
                validator={validator}
                flowStore={flowStore}
                onConnectGoogle={(credentials) => void actions.beginGoogleConnect(flowStore, credentials)}
              />
              {finishError && (
                <div 
                  className="mt-[var(--space-4)] p-[var(--space-3)] rounded-[var(--radius-control)] bg-[var(--error-bg)] border border-[var(--error)] flex items-start gap-[var(--space-2)]"
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
                  <span style={{ fontSize: "var(--text-body-size)" }}>
                    {finishError}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </OnboardingCardFrame>
    </div>
  );
}

