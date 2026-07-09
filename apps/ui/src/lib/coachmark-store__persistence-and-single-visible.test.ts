/**
 * Behaviour tests for coachmark-store.ts: the discoverability system
 * (redesign-brief-v2.md §5.2) promises "shown once" (persisted dismissal)
 * and "max one visible at a time" (first-registered wins, next queued shows
 * after dismiss). Both invariants are load-bearing enough to break the whole
 * onboarding-coachmark budget if either silently regresses.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { createCoachmarkStore, useCoachmark } from "./coachmark-store";

const STORAGE_KEY = "omni.coachmarks.v1";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("coachmark dismissal persistence", () => {
  it("starts with an empty dismissed set when localStorage is empty", () => {
    const store = createCoachmarkStore();
    expect(store.getState().dismissed.size).toBe(0);
  });

  it("loads previously dismissed ids from localStorage", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(["home.record-cta"]));
    const store = createCoachmarkStore();
    expect(store.getState().dismissed.has("home.record-cta")).toBe(true);
  });

  it("fails safe to an empty set on corrupted JSON (never crashes the store)", () => {
    window.localStorage.setItem(STORAGE_KEY, "{not valid json");
    const store = createCoachmarkStore();
    expect(store.getState().dismissed.size).toBe(0);
  });

  it("fails safe to an empty set when the stored value is valid JSON but not an array", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ unexpected: "shape" }));
    const store = createCoachmarkStore();
    expect(store.getState().dismissed.size).toBe(0);
  });

  it("drops non-string entries from a malformed array instead of failing the whole read", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(["good", 42, null, { bad: true }, "also-good"]));
    const store = createCoachmarkStore();
    expect([...store.getState().dismissed].sort()).toEqual(["also-good", "good"]);
  });

  it("persists a new dismissal to localStorage in the documented shape", () => {
    const store = createCoachmarkStore();
    const hook = renderHook(() => useCoachmark("captions-overlay", store));
    act(() => hook.result.current.dismiss());
    const raw = window.localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string)).toEqual(["captions-overlay"]);
  });

  it("is idempotent on a double dismiss — no duplicate entries, no throw", () => {
    const store = createCoachmarkStore();
    const hook = renderHook(() => useCoachmark("translate", store));
    expect(() => {
      act(() => {
        hook.result.current.dismiss();
        hook.result.current.dismiss();
      });
    }).not.toThrow();
    expect(store.getState().dismissed.size).toBe(1);
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]")).toEqual(["translate"]);
  });
});

describe("useCoachmark: at most one visible app-wide at a time", () => {
  it("shows only the first-registered coachmark when two mount together", () => {
    const store = createCoachmarkStore();
    const first = renderHook(() => useCoachmark("a", store));
    const second = renderHook(() => useCoachmark("b", store));
    expect(first.result.current.visible).toBe(true);
    expect(second.result.current.visible).toBe(false);
  });

  it("lets the next queued coachmark show after the visible one is dismissed", () => {
    const store = createCoachmarkStore();
    const first = renderHook(() => useCoachmark("a", store));
    const second = renderHook(() => useCoachmark("b", store));
    expect(second.result.current.visible).toBe(false);

    act(() => first.result.current.dismiss());
    second.rerender();
    expect(second.result.current.visible).toBe(true);
  });

  it("dismissing a QUEUED (not-yet-visible) coachmark records it permanently without disturbing the currently-visible one", () => {
    const store = createCoachmarkStore();
    const first = renderHook(() => useCoachmark("a", store));
    const second = renderHook(() => useCoachmark("b", store));
    expect(second.result.current.visible).toBe(false);

    act(() => second.result.current.dismiss());
    first.rerender();
    expect(first.result.current.visible).toBe(true); // unaffected
    expect(store.getState().dismissed.has("b")).toBe(true); // "b" never gets its turn now
  });

  it("persists dismissal so the id never becomes visible again, even after a full remount", () => {
    const store = createCoachmarkStore();
    const hook = renderHook(() => useCoachmark("a", store));
    act(() => hook.result.current.dismiss());
    hook.unmount();

    const remounted = renderHook(() => useCoachmark("a", store));
    expect(remounted.result.current.visible).toBe(false);
    expect(store.getState().dismissed.has("a")).toBe(true);
  });

  it("unregisters on unmount WITHOUT dismissing, so an id that was never seen can queue again", () => {
    const store = createCoachmarkStore();
    const first = renderHook(() => useCoachmark("a", store));
    expect(first.result.current.visible).toBe(true);
    first.unmount();
    expect(store.getState().dismissed.has("a")).toBe(false);
    expect(store.getState().queue.includes("a")).toBe(false);

    const remounted = renderHook(() => useCoachmark("a", store));
    expect(remounted.result.current.visible).toBe(true);
  });
});
