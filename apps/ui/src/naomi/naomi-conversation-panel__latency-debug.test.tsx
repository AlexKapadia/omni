/**
 * Latency table is a debug surface — hidden by default.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { NaomiConversationPanel } from "./naomi-conversation-panel";
import { initialNaomiConversationState } from "./naomi-conversation-store";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const noop = vi.fn();

describe("NaomiConversationPanel latency table", () => {
  it("hides the latency table by default", () => {
    render(
      <NaomiConversationPanel
        state={initialNaomiConversationState}
        engineConnected
        pushToTalkHeld={false}
        onPushToTalkDown={noop}
        onPushToTalkUp={noop}
        onToggleOpenMic={noop}
      />,
    );
    expect(screen.queryByTestId("naomi-latency-table")).toBeNull();
  });

  it("shows the latency table when debug flag is on", () => {
    localStorage.setItem("omni.naomi.debugLatency", "true");
    render(
      <NaomiConversationPanel
        state={initialNaomiConversationState}
        engineConnected
        pushToTalkHeld={false}
        onPushToTalkDown={noop}
        onPushToTalkUp={noop}
        onToggleOpenMic={noop}
      />,
    );
    expect(screen.getByTestId("naomi-latency-table")).toBeTruthy();
  });
});
