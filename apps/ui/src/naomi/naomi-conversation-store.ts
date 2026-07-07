/**
 * The Naomi conversation reducer: a PURE (no DOM, no React, no side effects)
 * state machine modelling one turn loop — listen → user_utterance → thinking
 * → reply → latency → speaking → (back to listening). It is the single place
 * the parsed turn events (naomi-turn-protocol.ts) and the local control
 * actions (push-to-talk / open-mic / connection-lost) fold into one shape the
 * view renders. Kept pure so it is exhaustively unit-testable.
 *
 * Sits above naomi-turn-protocol.ts (which validates the wire) and below
 * NaomiView.tsx (which drives it via useReducer and renders the result).
 */

import { clampAffect, type Affect } from "./naomi-affect-types";
import type {
  NaomiReplyCitation,
  NaomiReplyEvent,
  NaomiStateEvent,
  NaomiTurnErrorEvent,
  NaomiTurnLatencyEvent,
  NaomiTurnState,
  NaomiUserUtteranceEvent,
} from "./naomi-turn-protocol";

/** Shown when the engine socket drops mid-conversation (honest offline state). */
export const NAOMI_CONNECTION_LOST_MESSAGE =
  "Connection to the engine was lost. Voice needs the engine running.";

export interface NaomiConversationState {
  readonly turnState: NaomiTurnState;
  /** true = VAD-gated conversation (mic stays open); false = push-to-talk. */
  readonly openMic: boolean;
  /** Verbatim user speech for the current turn, or null before it lands. */
  readonly userText: string | null;
  readonly replyText: string | null;
  /** Reply affect, clamped into pool range; null when absent or dropped. */
  readonly affect: Affect | null;
  readonly citations: readonly NaomiReplyCitation[];
  /** Preserved across a fresh turn until the next reply's latency arrives. */
  readonly latency: NaomiTurnLatencyEvent | null;
  readonly noAnswer: boolean;
  readonly actionCardId: number | null;
  readonly error: string | null;
}

export const initialNaomiConversationState: NaomiConversationState = {
  turnState: "idle",
  openMic: false,
  userText: null,
  replyText: null,
  affect: null,
  citations: [],
  latency: null,
  noAnswer: false,
  actionCardId: null,
  error: null,
};

export type NaomiConversationAction =
  | { readonly type: "state"; readonly event: NaomiStateEvent }
  | { readonly type: "user_utterance"; readonly event: NaomiUserUtteranceEvent }
  | { readonly type: "reply"; readonly event: NaomiReplyEvent }
  | { readonly type: "latency"; readonly event: NaomiTurnLatencyEvent }
  | { readonly type: "turn_error"; readonly event: NaomiTurnErrorEvent }
  | { readonly type: "listen-start"; readonly openMic: boolean }
  | { readonly type: "listen-stop" }
  | { readonly type: "connection-lost" };

/**
 * Enter a fresh listening turn: clear the previous turn's content (spec:
 * user/reply/citations cleared) but PRESERVE the latency table so the last
 * turn's speed numbers stay on screen until the next reply replaces them.
 */
function beginFreshTurn(state: NaomiConversationState): NaomiConversationState {
  return {
    ...state,
    turnState: "listening",
    userText: null,
    replyText: null,
    affect: null,
    citations: [],
    noAnswer: false,
    actionCardId: null,
    error: null,
  };
}

/** Convert the wire affect triple into a clamped pool Affect (deny bad ranges). */
function toPoolAffect(event: NaomiReplyEvent): Affect | null {
  if (event.affect === null) return null;
  const burst = event.affect.burst === "laugh" ? { kind: "laugh" as const, intensity: 1 } : null;
  return clampAffect(event.affect.v, event.affect.a, burst);
}

export function naomiConversationReducer(
  state: NaomiConversationState,
  action: NaomiConversationAction,
): NaomiConversationState {
  switch (action.type) {
    case "state": {
      // A new listening state after a turn opens a fresh turn (clear content,
      // keep latency). Every other engine state simply moves the machine.
      if (action.event.state === "listening") return beginFreshTurn(state);
      return { ...state, turnState: action.event.state };
    }
    case "user_utterance":
      // Verbatim — the store never rewrites the user's words (fidelity mandate).
      return { ...state, userText: action.event.text };
    case "reply":
      return {
        ...state,
        replyText: action.event.text,
        affect: toPoolAffect(action.event),
        citations: action.event.citations,
        noAnswer: action.event.no_answer,
        actionCardId: action.event.action_card_id,
        error: null, // a reply landed: the turn succeeded, clear any stale error
      };
    case "latency":
      return { ...state, latency: action.event };
    case "turn_error":
      // Honest recovery: in open-mic the mic is still listening; in push-to-talk
      // the turn is over → idle. Never fake a success state on failure.
      return {
        ...state,
        error: action.event.message,
        turnState: state.openMic ? "listening" : "idle",
      };
    case "listen-start":
      // Local optimistic open; the engine's authoritative naomi.state follows.
      return { ...beginFreshTurn(state), openMic: action.openMic };
    case "listen-stop":
      // Close the mic loop locally; the engine's next state event is authoritative
      // (flush → thinking, discard → idle), so turnState is left for it to set.
      return { ...state, openMic: false };
    case "connection-lost":
      return {
        ...state,
        turnState: "idle",
        openMic: false,
        error: NAOMI_CONNECTION_LOST_MESSAGE,
      };
    default: {
      // Exhaustiveness guard: a new action type must be handled, not ignored.
      const _never: never = action;
      return state ?? _never;
    }
  }
}
