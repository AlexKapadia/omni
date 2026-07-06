/**
 * Approval-cards store tests: fail-closed parsing + status-from-events-only.
 *
 * Invariants under test (binding):
 * - A malformed card payload is dropped WHOLE — every deviation in the
 *   table below leaves the store untouched (untrusted inbound frames).
 * - OPTIMISTIC-FREE: approve/dismiss/retry never change a card's status
 *   locally; only card.updated events do.
 * - The instant-execute whitelist ships EMPTY (deny by default).
 */
import { describe, expect, it } from "vitest";
import {
  applyCardUpdated,
  applyCardsListReply,
  approveCard,
  createApprovalCardsStore,
  DEFAULT_INSTANT_EXECUTE_WHITELIST,
  dismissCard,
  ENGINE_OFFLINE_MESSAGE,
  parseApprovalCard,
  requestCardsList,
  retryCard,
} from "./approval-cards-store";

function validCard(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    meeting_id: "m-1",
    source: "extraction",
    card_type: "create_event",
    status: "pending",
    payload: { title: "Lunch with Tom", when_hint: "Friday at 1" },
    preview_lines: ["Event: Lunch with Tom"],
    created_at: "2026-07-06T12:00:00+00:00",
    decided_at: null,
    executed_at: null,
    error: null,
    result_summary: null,
    ...overrides,
  };
}

describe("parseApprovalCard (fail closed)", () => {
  it("accepts the exact pinned shape", () => {
    const card = parseApprovalCard(validCard());
    expect(card).not.toBeNull();
    expect(card?.cardType).toBe("create_event");
    expect(card?.previewLines).toEqual(["Event: Lunch with Tom"]);
  });

  it.each([
    ["not an object", "nope"],
    ["null", null],
    ["array", [validCard()]],
    ["id zero", validCard({ id: 0 })],
    ["id negative", validCard({ id: -3 })],
    ["id float", validCard({ id: 1.5 })],
    ["id string", validCard({ id: "1" })],
    ["unknown card_type", validCard({ card_type: "send_email" })],
    ["unknown status", validCard({ status: "shipped" })],
    ["unknown source", validCard({ source: "psychic" })],
    ["payload array", validCard({ payload: ["x"] })],
    ["payload string", validCard({ payload: "{}" })],
    ["preview not array", validCard({ preview_lines: "Event" })],
    ["preview with non-string", validCard({ preview_lines: ["ok", 7] })],
    ["created_at empty", validCard({ created_at: "" })],
    ["created_at number", validCard({ created_at: 123 })],
    ["decided_at number", validCard({ decided_at: 5 })],
    ["error object", validCard({ error: { boom: true } })],
    ["missing status", (() => { const c = validCard(); delete c["status"]; return c; })()],
  ])("rejects %s", (_label, payload) => {
    expect(parseApprovalCard(payload)).toBeNull();
  });
});

describe("applyCardsListReply", () => {
  it("keeps valid cards and drops malformed ones individually", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, {
      cards: [validCard({ id: 1 }), "garbage", validCard({ id: 2, status: "bogus" }), validCard({ id: 3 })],
    });
    expect(store.getState().loaded).toBe(true);
    expect(store.getState().cards.map((c) => c.id)).toEqual([1, 3]);
  });

  it("ignores a reply without a cards array (store untouched)", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, { cards: "nope" });
    applyCardsListReply(store, null);
    expect(store.getState().loaded).toBe(false);
    expect(store.getState().cards).toEqual([]);
  });
});

describe("status changes come ONLY from engine events (optimistic-free)", () => {
  it("approveCard marks in-flight but never flips the status", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, { cards: [validCard({ id: 7 })] });
    const sent = approveCard(7, undefined, store, () => true);
    expect(sent).toBe(true);
    expect(store.getState().cards[0]?.status).toBe("pending"); // NOT "approved"
    expect(store.getState().inFlightIds).toEqual([7]);
  });

  it("dismissCard and retryCard also leave status untouched", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, {
      cards: [validCard({ id: 7 }), validCard({ id: 8, status: "failed", error: "x" })],
    });
    dismissCard(7, store, () => true);
    retryCard(8, store, () => true);
    expect(store.getState().cards.map((c) => c.status)).toEqual(["pending", "failed"]);
    expect(store.getState().inFlightIds).toEqual([7, 8]);
  });

  it("card.updated is what moves the status and clears in-flight", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, { cards: [validCard({ id: 7 })] });
    approveCard(7, undefined, store, () => true);
    applyCardUpdated(store, {
      card: validCard({ id: 7, status: "approved", decided_at: "2026-07-06T12:01:00+00:00" }),
    });
    expect(store.getState().cards[0]?.status).toBe("approved");
    expect(store.getState().inFlightIds).toEqual([]);
    applyCardUpdated(store, {
      card: validCard({
        id: 7,
        status: "executed",
        decided_at: "2026-07-06T12:01:00+00:00",
        executed_at: "2026-07-06T12:01:02+00:00",
        result_summary: "Event created: Lunch with Tom",
      }),
    });
    expect(store.getState().cards[0]?.status).toBe("executed");
    expect(store.getState().cards[0]?.resultSummary).toBe("Event created: Lunch with Tom");
  });

  it("a malformed card.updated changes nothing", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, { cards: [validCard({ id: 7 })] });
    const before = store.getState();
    applyCardUpdated(store, { card: validCard({ id: 7, status: "hacked" }) });
    applyCardUpdated(store, { nope: true });
    applyCardUpdated(store, "junk");
    expect(store.getState()).toEqual(before);
  });

  it("an unseen card in card.updated is prepended (a new suggestion)", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, { cards: [validCard({ id: 1 })] });
    applyCardUpdated(store, { card: validCard({ id: 99 }) });
    expect(store.getState().cards.map((c) => c.id)).toEqual([99, 1]);
  });
});

describe("fail-closed sends (engine offline)", () => {
  it("requestCardsList surfaces the offline error instead of pretending", () => {
    const store = createApprovalCardsStore();
    const sent = requestCardsList(store, () => false);
    expect(sent).toBe(false);
    expect(store.getState().errorMessage).toBe(ENGINE_OFFLINE_MESSAGE);
  });

  it("a failed approve does not mark in-flight (nothing actually left)", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, { cards: [validCard({ id: 7 })] });
    const sent = approveCard(7, undefined, store, () => false);
    expect(sent).toBe(false);
    expect(store.getState().inFlightIds).toEqual([]);
    expect(store.getState().errorMessage).toBe(ENGINE_OFFLINE_MESSAGE);
  });
});

describe("approve with inline edit", () => {
  it("sends edited_payload with the approve command (one atomic decision)", () => {
    const store = createApprovalCardsStore();
    applyCardsListReply(store, { cards: [validCard({ id: 7 })] });
    const sends: Array<{ name: string; payload: Record<string, unknown> | undefined }> = [];
    approveCard(7, { title: "Lunch with Tom Reed" }, store, (name, payload) => {
      sends.push({ name, payload });
      return true;
    });
    expect(sends).toEqual([
      {
        name: "card.approve",
        payload: { id: 7, edited_payload: { title: "Lunch with Tom Reed" } },
      },
    ]);
  });

  it("plain approve carries no edited_payload key at all", () => {
    const store = createApprovalCardsStore();
    const sends: Array<Record<string, unknown> | undefined> = [];
    approveCard(7, undefined, store, (_name, payload) => {
      sends.push(payload);
      return true;
    });
    expect(sends[0]).toEqual({ id: 7 });
  });
});

describe("instant-execute whitelist placeholder", () => {
  it("ships EMPTY: everything needs approval until the user opts in", () => {
    expect(DEFAULT_INSTANT_EXECUTE_WHITELIST.instantExecuteCardTypes).toEqual([]);
  });
});
