/**
 * Settings screen tests: the binding key-masking invariant (a saved key
 * value NEVER appears anywhere in the DOM), privacy defaults (keep-audio
 * OFF), the kill-switch disclosure, real router-matrix radios with
 * deny-by-default cells, and the computed (never hand-written) ledger total.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SettingsScreen } from "./settings-screen";
import { createApiKeysStore, type ApiKeysStore } from "../lib/api-keys-store";
import { buildMockInitialSettings } from "../lib/mock-settings-data";
import {
  applyDeviceListing,
  createSettingsStore,
  type SettingsStore,
} from "../lib/settings-store";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);

afterEach(cleanup);

let settings: SettingsStore;
let keys: ApiKeysStore;

beforeEach(() => {
  settings = createSettingsStore(buildMockInitialSettings());
  keys = createApiKeysStore();
});

function renderScreen(vault = { persistKey: () => Promise.resolve() }) {
  // refreshDevices is injected as a noop: the engine socket does not exist
  // in jsdom; the real devices flow has its own suite (engine-devices).
  return render(
    <SettingsScreen
      store={settings}
      keysStore={keys}
      vault={vault}
      refreshDevices={() => Promise.resolve()}
    />,
  );
}

describe("API key masking (binding security invariant)", () => {
  const SECRET = "sk-ant-Zx9Qw7Rt5Yu3Io1PR2Qw";

  it("the saved key value NEVER appears in the DOM afterwards", async () => {
    renderScreen();
    const input = screen.getByLabelText("Claude API key") as HTMLInputElement;
    expect(input.type).toBe("password"); // masked while typing too
    fireEvent.change(input, { target: { value: SECRET } });
    const saveButtons = screen.getAllByRole("button", { name: "Save key" });
    await act(async () => {
      fireEvent.click(saveButtons[saveButtons.length - 1]!);
    });
    // The invariant: full plaintext is gone from the document, everywhere.
    expect(document.body.innerHTML).not.toContain(SECRET);
    // Only recognition metadata remains: mask + last four + Saved.
    expect(screen.getByText(/•+ R2Qw/)).toBeTruthy();
    expect(screen.getByText("Saved")).toBeTruthy();
    // The input itself is gone (replaced by the masked row), not just cleared.
    expect(screen.queryByLabelText("Claude API key")).toBeNull();
  });

  it("a too-short key is refused with visible copy and no Saved state", async () => {
    renderScreen();
    fireEvent.change(screen.getByLabelText("Groq API key"), { target: { value: "abc123" } });
    await act(async () => {
      fireEvent.click(screen.getAllByRole("button", { name: "Save key" })[0]!);
    });
    expect(screen.getByRole("alert").textContent).toContain("too short");
    expect(screen.queryByText("Saved")).toBeNull();
  });
});

describe("privacy controls", () => {
  it("keep-audio defaults OFF and toggling it updates the store", () => {
    renderScreen();
    const toggle = screen.getByRole("switch", { name: "Keep audio after transcription" });
    expect(toggle.getAttribute("aria-checked")).toBe("false"); // security default
    fireEvent.click(toggle);
    expect(settings.getState().keepAudio).toBe(true);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("kill switch discloses its effect in the router card when engaged", () => {
    renderScreen();
    expect(screen.queryByText(/Kill switch engaged/)).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Kill switch" }));
    expect(settings.getState().killSwitch).toBe(true);
    expect(screen.getByText(/every external route above is refused/)).toBeTruthy();
  });
});

describe("AI router matrix", () => {
  it("selecting an allowed provider updates the routing table", () => {
    renderScreen();
    const radio = screen.getByRole("radio", { name: "route live answers to claude" });
    expect(radio.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(radio);
    expect(radio.getAttribute("aria-checked")).toBe("true");
    expect(settings.getState().routing.find((r) => r.task === "live answers")?.provider).toBe(
      "claude",
    );
  });

  it("DENY BY DEFAULT: on-device tasks expose no cloud radio at all", () => {
    renderScreen();
    expect(screen.queryByRole("radio", { name: "route transcription to claude" })).toBeNull();
    expect(screen.queryByRole("radio", { name: "route embeddings to groq" })).toBeNull();
    // The local radio exists and is selected.
    expect(
      screen.getByRole("radio", { name: "route transcription to local" }).getAttribute("aria-checked"),
    ).toBe("true");
  });
});

describe("ledger", () => {
  it("renders the COMPUTED total row exactly (374 calls · 1.57M · $5.99)", () => {
    renderScreen();
    expect(screen.getByText("374")).toBeTruthy();
    expect(screen.getByText("1.57M")).toBeTruthy();
    expect(screen.getByText("$5.99")).toBeTruthy();
    // And it is honestly labelled as sample data.
    expect(screen.getByText(/sample data/)).toBeTruthy();
  });

  it("device select is real: choosing an engine-enumerated microphone updates the store", () => {
    // Devices start honest-empty; the select exists only once REAL
    // enumeration arrives (mock device names are retired).
    renderScreen();
    expect(screen.queryByLabelText("Microphone")).toBeNull();
    expect(screen.getAllByText("reading devices from the engine").length).toBeGreaterThan(0);
    act(() => {
      applyDeviceListing(settings, {
        microphone: "Default microphone",
        microphoneOptions: ["Default microphone", "Headset microphone"],
        systemAudioDevice: "Speakers (WASAPI loopback)",
      });
    });
    fireEvent.change(screen.getByLabelText("Microphone"), {
      target: { value: "Headset microphone" },
    });
    expect(settings.getState().microphone).toBe("Headset microphone");
    expect(screen.getByText("Speakers (WASAPI loopback)")).toBeTruthy();
  });
});
