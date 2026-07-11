/**
 * Tray "Record a meeting" must navigate to Live before starting capture.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

const requestCaptureStart = vi.fn();

vi.mock("./capture-commands", () => ({
  requestCaptureStart: (...args: unknown[]) => requestCaptureStart(...args),
}));

import { wireTrayStartCapture } from "./wire-tray-capture";

beforeEach(() => {
  requestCaptureStart.mockReset();
});

describe("wireTrayStartCapture", () => {
  it("calls onStart then requestCaptureStart when the tray event fires", async () => {
    const onStart = vi.fn();
    let handler: (() => void) | undefined;
    const listen = vi.fn(async (_event: string, h: () => void) => {
      handler = h;
      return () => undefined;
    });

    await wireTrayStartCapture(listen, onStart);
    expect(listen).toHaveBeenCalledWith("tray-start-capture", expect.any(Function));
    expect(handler).toBeDefined();

    handler!();
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(requestCaptureStart).toHaveBeenCalledTimes(1);
    expect(onStart.mock.invocationCallOrder[0]).toBeLessThan(
      requestCaptureStart.mock.invocationCallOrder[0]!,
    );
  });

  it("still starts capture when onStart is omitted", async () => {
    let handler: (() => void) | undefined;
    await wireTrayStartCapture(async (_event, h) => {
      handler = h;
      return () => undefined;
    });
    handler!();
    expect(requestCaptureStart).toHaveBeenCalledTimes(1);
  });
});
