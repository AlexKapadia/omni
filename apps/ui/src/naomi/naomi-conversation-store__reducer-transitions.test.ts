/**
 * The conversation reducer is the turn-loop's brain — this proves the exact
 * state shape at every step of a full turn, the clear-on-new-turn rule (with
 * latency deliberately preserved), no-answer honesty, and honest error
 * recovery (push-to-talk → idle, open-mic → listening). Pure in / pure out.
 */
import { describe, expect, it } from "vitest";
import {
  NAOMI_CONNECTION_LOST_MESSAGE,
  initialNaomiConversationState,
  naomiConversationReducer,
  type NaomiConversationAction,
  type NaomiConversationState,
} from "./naomi-conversation-store";
import type {
  NaomiReplyEvent,
  NaomiTurnLatencyEvent,
} from "./naomi-turn-protocol";

/** Fold a sequence of actions from a start state (readable transition tests). */
function run(
  start: NaomiConversationState,
  actions: readonly NaomiConversationAction[],
): NaomiConversationState {
  return actions.reduce(naomiConversationReducer, start);
}

const CITATION = {
  n: 1,
  note_path: "Notes/Sync.md",
  line_start: 3,
  line_end: 5,
  heading_path: "Decisions",
  quote: "Ship Friday.",
};

const REPLY: NaomiReplyEvent = {
  turn_id: "t1",
  text: "You agreed to ship Friday. [1]",
  affect: { v: 0.4, a: 0.5, burst: "laugh" },
  no_answer: false,
  citations: [CITATION],
  action_card_id: 7,
};

const LATENCY: NaomiTurnLatencyEvent = {
  turn_id: "t1",
  endpoint_ms: 120,
  retrieval_ms: 40,
  llm_ms: 300,
  ttfa_ms: 220,
  total_ms: 460,
};

describe("a full turn walks the machine correctly", () => {
  it("listen → utterance → thinking → reply → latency → speaking", () => {
    const s0 = initialNaomiConversationState;
    expect(s0.turnState).toBe("idle");

    const s1 = naomiConversationReducer(s0, { type: "state", event: { state: "listening", turn_id: "t1" } });
    expect(s1.turnState).toBe("listening");

    const s2 = naomiConversationReducer(s1, {
      type: "user_utterance",
      event: { turn_id: "t1", text: "what did i decide about shipping?" },
    });
    expect(s2.userText).toBe("what did i decide about shipping?"); // verbatim

    const s3 = naomiConversationReducer(s2, { type: "state", event: { state: "thinking", turn_id: "t1" } });
    expect(s3.turnState).toBe("thinking");
    expect(s3.userText).toBe("what did i decide about shipping?"); // preserved

    const s4 = naomiConversationReducer(s3, { type: "reply", event: REPLY });
    expect(s4.replyText).toBe(REPLY.text);
    expect(s4.citations).toEqual([CITATION]);
    expect(s4.noAnswer).toBe(false);
    expect(s4.actionCardId).toBe(7);
    // Reply affect is clamped into pool space with a laugh burst object.
    expect(s4.affect).toEqual({ valence: 0.4, arousal: 0.5, burst: { kind: "laugh", intensity: 1 } });

    const s5 = naomiConversationReducer(s4, { type: "latency", event: LATENCY });
    expect(s5.latency).toEqual(LATENCY);

    const s6 = naomiConversationReducer(s5, { type: "state", event: { state: "speaking", turn_id: "t1" } });
    expect(s6.turnState).toBe("speaking");
    expect(s6.replyText).toBe(REPLY.text); // still on screen while she speaks
  });
});

describe("a fresh listening turn clears content but preserves the latency table", () => {
  it("wipes user/reply/citations, keeps latency until the next reply", () => {
    const primed = run(initialNaomiConversationState, [
      { type: "state", event: { state: "listening", turn_id: "t1" } },
      { type: "user_utterance", event: { turn_id: "t1", text: "hi" } },
      { type: "reply", event: REPLY },
      { type: "latency", event: LATENCY },
      { type: "state", event: { state: "speaking", turn_id: "t1" } },
    ]);
    expect(primed.latency).toEqual(LATENCY);

    // The next turn opens with state=listening again.
    const fresh = naomiConversationReducer(primed, {
      type: "state",
      event: { state: "listening", turn_id: "t2" },
    });
    expect(fresh.turnState).toBe("listening");
    expect(fresh.userText).toBeNull();
    expect(fresh.replyText).toBeNull();
    expect(fresh.citations).toEqual([]);
    expect(fresh.affect).toBeNull();
    expect(fresh.actionCardId).toBeNull();
    // Latency survives the fresh turn (last turn's numbers stay visible).
    expect(fresh.latency).toEqual(LATENCY);
  });
});

describe("no-answer honesty", () => {
  it("carries the honest flag with no citations and no card", () => {
    const s = naomiConversationReducer(initialNaomiConversationState, {
      type: "reply",
      event: {
        turn_id: "t1",
        text: "That isn't in your notes.",
        affect: null,
        no_answer: true,
        citations: [],
        action_card_id: null,
      },
    });
    expect(s.noAnswer).toBe(true);
    expect(s.citations).toEqual([]);
    expect(s.actionCardId).toBeNull();
    expect(s.affect).toBeNull();
  });
});

describe("local controls set the mic mode", () => {
  it("push-to-talk start opens a listening turn without open-mic", () => {
    const s = naomiConversationReducer(initialNaomiConversationState, {
      type: "listen-start",
      openMic: false,
    });
    expect(s.turnState).toBe("listening");
    expect(s.openMic).toBe(false);
  });
  it("open-mic start sets the conversation flag", () => {
    const s = naomiConversationReducer(initialNaomiConversationState, {
      type: "listen-start",
      openMic: true,
    });
    expect(s.openMic).toBe(true);
  });
  it("listen-stop closes the mic loop", () => {
    const opened = naomiConversationReducer(initialNaomiConversationState, {
      type: "listen-start",
      openMic: true,
    });
    expect(naomiConversationReducer(opened, { type: "listen-stop" }).openMic).toBe(false);
  });
});

describe("honest error recovery", () => {
  it("push-to-talk error returns to idle", () => {
    const ptt = naomiConversationReducer(initialNaomiConversationState, {
      type: "listen-start",
      openMic: false,
    });
    const errored = naomiConversationReducer(ptt, {
      type: "turn_error",
      event: { message: "provider timed out", turn_id: "t1" },
    });
    expect(errored.error).toBe("provider timed out");
    expect(errored.turnState).toBe("idle");
  });
  it("open-mic error returns to listening (mic still open)", () => {
    const open = naomiConversationReducer(initialNaomiConversationState, {
      type: "listen-start",
      openMic: true,
    });
    const errored = naomiConversationReducer(open, {
      type: "turn_error",
      event: { message: "retrieval failed", turn_id: null },
    });
    expect(errored.turnState).toBe("listening");
    expect(errored.error).toBe("retrieval failed");
  });
  it("a later successful reply clears a stale error", () => {
    const errored = naomiConversationReducer(initialNaomiConversationState, {
      type: "turn_error",
      event: { message: "boom", turn_id: null },
    });
    expect(errored.error).toBe("boom");
    const recovered = naomiConversationReducer(errored, { type: "reply", event: REPLY });
    expect(recovered.error).toBeNull();
  });
  it("connection-lost goes idle and surfaces the offline message", () => {
    const open = naomiConversationReducer(initialNaomiConversationState, {
      type: "listen-start",
      openMic: true,
    });
    const lost = naomiConversationReducer(open, { type: "connection-lost" });
    expect(lost.turnState).toBe("idle");
    expect(lost.openMic).toBe(false);
    expect(lost.error).toBe(NAOMI_CONNECTION_LOST_MESSAGE);
  });
});
