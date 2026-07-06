/**
 * Adversarial tests for the Ask store: full state lifecycle, exact citation
 * pass-through, and the out-of-order response guard — a slow stale answer
 * must NEVER clobber a newer question's result.
 */
import { describe, expect, it } from "vitest";
import {
  askQuestion,
  createAskStore,
  toggleCitation,
  type AskAnswer,
} from "./ask-store";

const ANSWER_A: AskAnswer = {
  headline: "A",
  prose: [{ text: "answer a" }],
  citations: [
    { marker: 1, notePath: "vault/a.md", lineStart: 1, lineEnd: 2, headingPath: "A", snippet: "sa" },
  ],
};
const ANSWER_B: AskAnswer = { headline: "B", prose: [{ text: "answer b" }], citations: [] };

describe("ask lifecycle", () => {
  it("empty -> thinking -> answered, with citations passed through exactly", async () => {
    const store = createAskStore();
    const pending = askQuestion(store, { answer: () => Promise.resolve(ANSWER_A) }, "q?");
    expect(store.getState().status).toBe("thinking");
    expect(store.getState().question).toBe("q?");
    await pending;
    expect(store.getState().status).toBe("answered");
    expect(store.getState().answer).toEqual(ANSWER_A); // exact, field for field
  });

  it("a whitespace-only question is refused outright (no thinking flash)", async () => {
    const store = createAskStore();
    await askQuestion(store, { answer: () => Promise.resolve(ANSWER_A) }, "   ");
    expect(store.getState().status).toBe("empty");
  });

  it("a rejecting provider lands in error with the real message", async () => {
    const store = createAskStore();
    await askQuestion(store, { answer: () => Promise.reject(new Error("index cold")) }, "q");
    expect(store.getState().status).toBe("error");
    expect(store.getState().errorMessage).toBe("index cold");
    expect(store.getState().answer).toBeNull(); // never a half-answer with an error
  });

  it("STALE GUARD: a slow first answer must not clobber the newer question", async () => {
    const store = createAskStore();
    let releaseFirst: (a: AskAnswer) => void = () => undefined;
    const firstGate = new Promise<AskAnswer>((resolve) => {
      releaseFirst = resolve;
    });
    const first = askQuestion(store, { answer: () => firstGate }, "first question");
    const second = askQuestion(store, { answer: () => Promise.resolve(ANSWER_B) }, "second question");
    await second;
    expect(store.getState().answer?.headline).toBe("B");
    releaseFirst(ANSWER_A); // the stale response finally arrives…
    await first;
    // …and must be discarded: the second answer stands.
    expect(store.getState().answer?.headline).toBe("B");
    expect(store.getState().question).toBe("second question");
  });

  it("STALE GUARD: a stale REJECTION must not paint an error over a fresh answer", async () => {
    const store = createAskStore();
    let rejectFirst: (e: Error) => void = () => undefined;
    const firstGate = new Promise<AskAnswer>((_resolve, reject) => {
      rejectFirst = reject;
    });
    const first = askQuestion(store, { answer: () => firstGate }, "first");
    await askQuestion(store, { answer: () => Promise.resolve(ANSWER_B) }, "second");
    rejectFirst(new Error("stale failure"));
    await first;
    expect(store.getState().status).toBe("answered");
    expect(store.getState().errorMessage).toBeNull();
  });

  it("citation toggle opens, switches and closes; a new question resets it", async () => {
    const store = createAskStore();
    await askQuestion(store, { answer: () => Promise.resolve(ANSWER_A) }, "q");
    toggleCitation(store, 1);
    expect(store.getState().openCitationMarker).toBe(1);
    toggleCitation(store, 2);
    expect(store.getState().openCitationMarker).toBe(2);
    toggleCitation(store, 2);
    expect(store.getState().openCitationMarker).toBeNull();
    toggleCitation(store, 1);
    await askQuestion(store, { answer: () => Promise.resolve(ANSWER_B) }, "q2");
    expect(store.getState().openCitationMarker).toBeNull();
  });
});
