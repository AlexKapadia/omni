/**
 * Toast queue tests: a bounded stack, auto-dismiss on a timer, and manual
 * dismiss by id. Uses a fresh store per test (the factory) so timers from one
 * test never leak state into another.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createToastStore, dismissToast, showToast } from "./toast-store";

describe("showToast / dismissToast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("adds a toast with the given message and variant", () => {
    const store = createToastStore();
    showToast("Pulled llama3.2.", "success", store, 0);

    const toasts = store.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({ message: "Pulled llama3.2.", variant: "success" });
  });

  it("defaults to the info variant", () => {
    const store = createToastStore();
    showToast("Opened the models folder.", undefined, store, 0);
    expect(store.getState().toasts[0]?.variant).toBe("info");
  });

  it("keeps only the last 3 toasts (bounded stack)", () => {
    const store = createToastStore();
    showToast("one", "info", store, 0);
    showToast("two", "info", store, 0);
    showToast("three", "info", store, 0);
    showToast("four", "info", store, 0);

    const messages = store.getState().toasts.map((t) => t.message);
    expect(messages).toEqual(["two", "three", "four"]);
  });

  it("auto-dismisses after the given delay", () => {
    const store = createToastStore();
    showToast("temporary", "info", store, 4000);
    expect(store.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(3999);
    expect(store.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(1);
    expect(store.getState().toasts).toHaveLength(0);
  });

  it("never auto-dismisses when autoDismissMs is 0", () => {
    const store = createToastStore();
    showToast("sticky", "error", store, 0);
    vi.advanceTimersByTime(60_000);
    expect(store.getState().toasts).toHaveLength(1);
  });

  it("dismissToast removes only the matching id", () => {
    const store = createToastStore();
    const firstId = showToast("first", "info", store, 0);
    showToast("second", "info", store, 0);

    dismissToast(firstId, store);

    const messages = store.getState().toasts.map((t) => t.message);
    expect(messages).toEqual(["second"]);
  });

  it("dismissing an unknown id is a harmless no-op", () => {
    const store = createToastStore();
    showToast("first", "info", store, 0);
    dismissToast("toast-does-not-exist", store);
    expect(store.getState().toasts).toHaveLength(1);
  });

  it("each toast gets a distinct id even with identical messages", () => {
    const store = createToastStore();
    const idA = showToast("dup", "info", store, 0);
    const idB = showToast("dup", "info", store, 0);
    expect(idA).not.toBe(idB);
  });
});
