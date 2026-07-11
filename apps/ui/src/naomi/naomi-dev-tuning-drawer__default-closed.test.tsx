/**
 * Dev tuning drawer starts collapsed — not open by default.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { NaomiDevTuningDrawer } from "./naomi-dev-tuning-drawer";

afterEach(cleanup);

describe("NaomiDevTuningDrawer", () => {
  it("starts closed (aria-expanded false, presets hidden)", () => {
    render(
      <NaomiDevTuningDrawer
        valence={0}
        arousal={0.1}
        onAffectChange={vi.fn()}
        micEnabled={false}
        onMicToggle={vi.fn()}
        stats={null}
        engineConnected={false}
        ttfaMs={null}
        speaking={false}
        lastError={null}
        onSay={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const toggle = screen.getByRole("button", { name: /Tuning/i });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: "Idle" })).toBeNull();
  });
});
