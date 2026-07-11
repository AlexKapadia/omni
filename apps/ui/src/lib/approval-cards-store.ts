/**
 * Zustand store for the post-meeting approval rack (design §05), fed by the
 * engine's approval-card protocol (engine/agents/approval_protocol_names.py).
 *
 * WIRING (DEFERRED — orchestrator connects at reconciliation): the WS event
 * dispatcher calls applyCardUpdated(approvalCardsStore, envelope.payload) for
 * events named CARD_UPDATED_EVENT_NAME, and applyCardsListReply(...) for the
 * CARDS_LIST_COMMAND_NAME reply.
 *
 * Security / honesty invariants (binding):
 * - OPTIMISTIC-FREE: approve/dismiss NEVER mutate a card's status locally.
 *   Status changes arrive exclusively via card.updated events from the
 *   engine — the UI can show "in flight", but the truth is the engine's
 *   (approval-before-execute: the schema decides, the UI reflects).
 * - Fail-closed parsing: a malformed card payload is dropped whole; it
 *   never half-populates the rack (untrusted inbound frame rule).
 * - The instant-execute whitelist below defaults to EMPTY: every action
 *   requires an approval card until the user explicitly opts in (deny by
 *   default; the settings wiring lands later).
 */
import { createStore, useStore, type StoreApi } from "zustand";
import { sendEngineCommand } from "./live-engine-socket";

/** Message names pinned with the engine (approval_protocol_names.py). */
export const CARDS_LIST_COMMAND_NAME = "cards.list";
export const CARD_APPROVE_COMMAND_NAME = "card.approve";
export const CARD_DISMISS_COMMAND_NAME = "card.dismiss";
export const CARD_RETRY_COMMAND_NAME = "card.retry";
export const CARD_UPDATED_EVENT_NAME = "card.updated";

export const ENGINE_OFFLINE_MESSAGE =
  "The engine is offline. Card actions need the engine running on this device.";

export type CommandSender = (name: string, payload?: Record<string, unknown>) => boolean;

export const APPROVAL_CARD_TYPES = [
  "create_event",
  "find_slot",
  "upsert_contact",
  "write_note",
  "draft_email",
] as const;
export type ApprovalCardType = (typeof APPROVAL_CARD_TYPES)[number];

export const APPROVAL_CARD_STATUSES = [
  "pending",
  "approved",
  "executing",
  "executed",
  "failed",
  "dismissed",
] as const;
export type ApprovalCardStatus = (typeof APPROVAL_CARD_STATUSES)[number];

const CARD_SOURCES = ["extraction", "dictation"] as const;
export type ApprovalCardSource = (typeof CARD_SOURCES)[number];

/** Mono-caps rack labels per design §05 ("CREATE EVENT" / "SAVE CONTACT" …). */
export const CARD_TYPE_LABELS: Readonly<Record<ApprovalCardType, string>> = {
  create_event: "CREATE EVENT",
  find_slot: "FIND TIME",
  upsert_contact: "SAVE CONTACT",
  write_note: "SAVE NOTE",
  draft_email: "DRAFT EMAIL",
};

export interface ApprovalCard {
  readonly id: number;
  readonly meetingId: string | null;
  readonly source: ApprovalCardSource;
  readonly cardType: ApprovalCardType;
  readonly status: ApprovalCardStatus;
  /** The typed payload as sent by the engine; edited copies ride approve. */
  readonly payload: Readonly<Record<string, unknown>>;
  /** Engine-rendered dry-run preview — the UI never invents a preview. */
  readonly previewLines: readonly string[];
  readonly createdAt: string;
  readonly decidedAt: string | null;
  readonly executedAt: string | null;
  /** Plain-voice failure reason (status "failed" only). */
  readonly error: string | null;
  /** Tool summary line (status "executed" only). */
  readonly resultSummary: string | null;
}

export interface ApprovalCardsState {
  /** Newest first, as the engine lists them. */
  readonly cards: readonly ApprovalCard[];
  /** True once a cards.list reply has been applied (loading vs empty). */
  readonly loaded: boolean;
  /** Ids with a decision in flight — buttons disable; status stays honest. */
  readonly inFlightIds: readonly number[];
  readonly errorMessage: string | null;
}

export const INITIAL_APPROVAL_CARDS_STATE: ApprovalCardsState = {
  cards: [],
  loaded: false,
  inFlightIds: [],
  errorMessage: null,
};

export type ApprovalCardsStore = StoreApi<ApprovalCardsState>;

export function createApprovalCardsStore(): ApprovalCardsStore {
  return createStore<ApprovalCardsState>(() => INITIAL_APPROVAL_CARDS_STATE);
}

/** The one store the running app uses. Tests create their own. */
export const approvalCardsStore: ApprovalCardsStore = createApprovalCardsStore();

export function useApprovalCards<T>(selector: (state: ApprovalCardsState) => T): T {
  return useStore(approvalCardsStore, selector);
}

/**
 * Instant-execute whitelist — persisted in app settings and consulted by the
 * engine for dictation intents (deny by default). The UI toggles write the
 * real `instant_execute_whitelist` setting; empty means every action needs a card.
 */
export interface InstantExecuteWhitelistSettings {
  readonly instantExecuteCardTypes: readonly ApprovalCardType[];
}

export const DEFAULT_INSTANT_EXECUTE_WHITELIST: InstantExecuteWhitelistSettings = {
  instantExecuteCardTypes: [], // deny by default — approval for everything
};

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

/**
 * Validate one card payload against the pinned engine contract. Returns
 * null on ANY deviation (fail closed) — a malformed card never renders.
 */
export function parseApprovalCard(value: unknown): ApprovalCard | null {
  if (!isPlainObject(value)) return null;
  const {
    id,
    meeting_id,
    source,
    card_type,
    status,
    payload,
    preview_lines,
    created_at,
    decided_at,
    executed_at,
    error,
    result_summary,
  } = value;
  if (typeof id !== "number" || !Number.isInteger(id) || id <= 0) return null;
  if (!isNullableString(meeting_id)) return null;
  if (typeof source !== "string" || !(CARD_SOURCES as readonly string[]).includes(source)) {
    return null;
  }
  if (
    typeof card_type !== "string" ||
    !(APPROVAL_CARD_TYPES as readonly string[]).includes(card_type)
  ) {
    return null;
  }
  if (
    typeof status !== "string" ||
    !(APPROVAL_CARD_STATUSES as readonly string[]).includes(status)
  ) {
    return null;
  }
  if (!isPlainObject(payload)) return null;
  if (!Array.isArray(preview_lines) || preview_lines.some((l) => typeof l !== "string")) {
    return null;
  }
  if (typeof created_at !== "string" || created_at.length === 0) return null;
  if (!isNullableString(decided_at) || !isNullableString(executed_at)) return null;
  if (!isNullableString(error) || !isNullableString(result_summary)) return null;
  return {
    id,
    meetingId: meeting_id ?? null,
    source: source as ApprovalCardSource,
    cardType: card_type as ApprovalCardType,
    status: status as ApprovalCardStatus,
    payload,
    previewLines: preview_lines as string[],
    createdAt: created_at,
    decidedAt: decided_at ?? null,
    executedAt: executed_at ?? null,
    error: error ?? null,
    resultSummary: result_summary ?? null,
  };
}

/**
 * Apply a cards.list reply: every entry is validated independently and
 * malformed entries are DROPPED (fail closed per card) — one corrupt card
 * must not blank the whole rack, and must never render half-parsed.
 */
export function applyCardsListReply(store: ApprovalCardsStore, payload: unknown): void {
  if (!isPlainObject(payload) || !Array.isArray(payload["cards"])) return;
  const cards = payload["cards"]
    .map(parseApprovalCard)
    .filter((card): card is ApprovalCard => card !== null);
  store.setState({ cards, loaded: true, errorMessage: null });
}

/**
 * Apply one card.updated event: upsert by id. THIS is the only place a
 * card's status ever changes (optimistic-free invariant); the in-flight
 * mark for that id clears because the engine has now spoken.
 */
export function applyCardUpdated(store: ApprovalCardsStore, payload: unknown): void {
  if (!isPlainObject(payload)) return;
  const card = parseApprovalCard(payload["card"]);
  if (card === null) return; // fail closed: malformed frames change nothing
  store.setState((state) => {
    const exists = state.cards.some((existing) => existing.id === card.id);
    return {
      cards: exists
        ? state.cards.map((existing) => (existing.id === card.id ? card : existing))
        : [card, ...state.cards],
      inFlightIds: state.inFlightIds.filter((id) => id !== card.id),
    };
  });
}

export function requestCardsList(
  store: ApprovalCardsStore = approvalCardsStore,
  send: CommandSender = sendEngineCommand,
): boolean {
  const sent = send(CARDS_LIST_COMMAND_NAME, {});
  if (!sent) {
    // Fail closed: no engine, no rack — say so instead of pretending.
    store.setState({ errorMessage: ENGINE_OFFLINE_MESSAGE });
  }
  return sent;
}

function sendDecision(
  name: string,
  cardId: number,
  extra: Record<string, unknown>,
  store: ApprovalCardsStore,
  send: CommandSender,
): boolean {
  const sent = send(name, { id: cardId, ...extra });
  store.setState((state) => ({
    // Status is NOT touched here — only the engine's card.updated moves it.
    inFlightIds: sent
      ? state.inFlightIds.includes(cardId)
        ? state.inFlightIds
        : [...state.inFlightIds, cardId]
      : state.inFlightIds,
    errorMessage: sent ? state.errorMessage : ENGINE_OFFLINE_MESSAGE,
  }));
  return sent;
}

/** Approve a card, optionally with the user's inline pre-approval edit. */
export function approveCard(
  cardId: number,
  editedPayload?: Record<string, unknown>,
  store: ApprovalCardsStore = approvalCardsStore,
  send: CommandSender = sendEngineCommand,
): boolean {
  const extra = editedPayload === undefined ? {} : { edited_payload: editedPayload };
  return sendDecision(CARD_APPROVE_COMMAND_NAME, cardId, extra, store, send);
}

export function dismissCard(
  cardId: number,
  store: ApprovalCardsStore = approvalCardsStore,
  send: CommandSender = sendEngineCommand,
): boolean {
  return sendDecision(CARD_DISMISS_COMMAND_NAME, cardId, {}, store, send);
}

/** Retry a FAILED card (the engine clones it — failed rows are immutable). */
export function retryCard(
  cardId: number,
  store: ApprovalCardsStore = approvalCardsStore,
  send: CommandSender = sendEngineCommand,
): boolean {
  return sendDecision(CARD_RETRY_COMMAND_NAME, cardId, {}, store, send);
}

/**
 * Clear one card's in-flight mark without changing status (optimistic-free).
 * Used when a decision is abandoned locally before the engine speaks.
 */
export function clearInFlight(
  store: ApprovalCardsStore,
  cardId: number,
): void {
  store.setState((state) => ({
    inFlightIds: state.inFlightIds.filter((id) => id !== cardId),
  }));
}

/**
 * A card.approve / dismiss / retry was refused: unstick the button and surface
 * the engine's honest reason. Status stays whatever card.updated last said.
 */
export function applyCardCommandError(
  store: ApprovalCardsStore,
  cardId: number,
  message: string,
): void {
  store.setState((state) => ({
    inFlightIds: state.inFlightIds.filter((id) => id !== cardId),
    errorMessage: message,
  }));
}

/**
 * Apply a card_error reply envelope payload. Clears every stuck in-flight mark
 * (replies are not correlated by card id on this surface) and sets errorMessage.
 */
export function applyCardErrorReply(store: ApprovalCardsStore, payload: unknown): void {
  if (!isPlainObject(payload) || payload["code"] !== "card_error") return;
  const message =
    typeof payload["message"] === "string" && payload["message"].length > 0
      ? payload["message"]
      : "Card action failed";
  store.setState({ inFlightIds: [], errorMessage: message });
}

/** Wiring calls this when the engine connection drops (stale rack honesty). */
export function clearApprovalCards(store: ApprovalCardsStore = approvalCardsStore): void {
  store.setState(INITIAL_APPROVAL_CARDS_STATE, true);
}
