/**
 * Reconciliation wiring for the "intelligence" event surfaces sharing the
 * one engine socket: live answers (answers.hit), meeting detection
 * (meeting.detected / capture.suggest_stop), the finalize flow's enhance.*
 * progress events, and the Ask screen's real request/reply transport.
 *
 * Registered as an additional frame listener by startLiveEngineConnection —
 * the capture/transcript dispatcher is untouched and its contract intact.
 *
 * Security invariant: every frame is untrusted; parseInboundMessage first,
 * per-store fail-closed payload parsing second, unknown events ignored
 * (deny by default, no speculative handling).
 */
import {
  applyCardsListReply,
  applyCardUpdated,
  approvalCardsStore,
  CARD_UPDATED_EVENT_NAME,
  type ApprovalCardsStore,
} from "./approval-cards-store";
import { setAskQueryTransport } from "./engine-ask-answer-provider";
import { createEngineAskTransport } from "./engine-ask-transport";
import {
  ANSWERS_HIT_EVENT_NAME,
  applyAnswersHit,
  clearLiveAnswers,
  liveAnswersStore,
  type LiveAnswersStore,
} from "./live-answers-store";
import {
  SUMMARY_UPDATED_EVENT_NAME,
  applySummaryUpdated,
  clearLiveSummary,
  liveSummaryStore,
  type LiveSummaryStore,
} from "./live-summary-store";
import {
  VAULT_SUGGESTION_EVENT_NAME,
  applyVaultSuggestion,
  clearVaultSuggestions,
  vaultSuggestionsStore,
  type VaultSuggestionsStore,
} from "./vault-suggestions-store";
import { CAPTURE_STARTED_EVENT_NAME } from "./capture-protocol";
import { maybeAutoStartCaptureOnDetection } from "./auto-start-reaction";
import {
  applyCaptureSuggestStop,
  applyMeetingDetected,
  CAPTURE_SUGGEST_STOP_EVENT_NAME,
  clearMeetingDetection,
  MEETING_DETECTED_EVENT_NAME,
  meetingDetectionStore,
  parseMeetingDetectedPayload,
  type MeetingDetectionStore,
} from "./meeting-detection-store";
import {
  applyEnhanceFailed,
  applyEnhanceReady,
  ENHANCE_FAILED_EVENT_NAME,
  ENHANCE_READY_EVENT_NAME,
  meetingFinalizeStore,
  resetMeetingFinalize,
  type MeetingFinalizeStore,
} from "./meeting-finalize-store";
import { parseInboundMessage } from "./protocol";

export interface IntelligenceStores {
  readonly liveAnswers: LiveAnswersStore;
  readonly liveSummary: LiveSummaryStore;
  readonly vaultSuggestions: VaultSuggestionsStore;
  readonly detection: MeetingDetectionStore;
  readonly finalize: MeetingFinalizeStore;
  readonly approvalCards: ApprovalCardsStore;
}

/**
 * Route one raw inbound frame to the intelligence stores. Exported as a
 * factory so tests drive isolated stores with raw frames.
 */
export function createIntelligenceFrameListener(
  stores: IntelligenceStores,
): (data: unknown) => void {
  return (data: unknown) => {
    const result = parseInboundMessage(data);
    if (!result.ok) return; // fail closed
    if (result.envelope.kind === "reply") {
      // The store fires cards.list without id bookkeeping (send-and-listen);
      // its ok-reply is the ONLY reply on this surface carrying a `cards`
      // array, so route by that shape. Parsing stays fail-closed per card
      // inside applyCardsListReply.
      const replyPayload = result.envelope.payload;
      if (result.envelope.name === "ok" && Array.isArray(replyPayload["cards"])) {
        applyCardsListReply(stores.approvalCards, replyPayload);
      }
      return;
    }
    if (result.envelope.kind !== "event") return;
    const { name, payload } = result.envelope;
    if (name === CARD_UPDATED_EVENT_NAME) {
      // Status truth for the approval rack (optimistic-free invariant).
      applyCardUpdated(stores.approvalCards, payload);
    } else if (name === ANSWERS_HIT_EVENT_NAME) {
      applyAnswersHit(stores.liveAnswers, payload);
    } else if (name === SUMMARY_UPDATED_EVENT_NAME) {
      applySummaryUpdated(stores.liveSummary, payload);
    } else if (name === VAULT_SUGGESTION_EVENT_NAME) {
      applyVaultSuggestion(stores.vaultSuggestions, payload);
    } else if (name === CAPTURE_STARTED_EVENT_NAME) {
      // A fresh meeting: hits belong to one meeting, the suggestion card is
      // consumed, and any previous finalize flow is over.
      clearLiveAnswers(stores.liveAnswers);
      clearLiveSummary(stores.liveSummary);
      clearVaultSuggestions(stores.vaultSuggestions);
      clearMeetingDetection(stores.detection);
      resetMeetingFinalize(stores.finalize);
    } else if (name === MEETING_DETECTED_EVENT_NAME) {
      applyMeetingDetected(stores.detection, payload);
      const suggestion = parseMeetingDetectedPayload(payload);
      if (suggestion !== null) {
        maybeAutoStartCaptureOnDetection(suggestion);
      }
    } else if (name === CAPTURE_SUGGEST_STOP_EVENT_NAME) {
      applyCaptureSuggestStop(stores.detection, payload);
    } else if (name === ENHANCE_READY_EVENT_NAME) {
      applyEnhanceReady(stores.finalize, payload);
    } else if (name === ENHANCE_FAILED_EVENT_NAME) {
      applyEnhanceFailed(stores.finalize, payload);
    }
    // Unknown events are ignored — deny by default, no speculative handling.
  };
}

let wired = false;

/**
 * One-time wiring against the app-singleton stores + the shared socket:
 * the frame listener above plus the Ask screen's real transport.
 * Idempotent — safe under React StrictMode double-mount.
 */
export function wireLiveIntelligence(
  subscribeFrames: (listener: (data: unknown) => void) => () => void,
): void {
  if (wired) return;
  wired = true;
  subscribeFrames(
    createIntelligenceFrameListener({
      liveAnswers: liveAnswersStore,
      liveSummary: liveSummaryStore,
      vaultSuggestions: vaultSuggestionsStore,
      detection: meetingDetectionStore,
      finalize: meetingFinalizeStore,
      approvalCards: approvalCardsStore,
    }),
  );
  // Ask goes live: the provider's honest offline rejection now only fires
  // when the socket itself is down, not because nothing was ever wired.
  setAskQueryTransport(createEngineAskTransport());
}
