/**
 * wireAutoSummary tests: finalize fires exactly when autoSummary is on, a
 * real capture.stopped event arrives, and no finalize flow is already
 * pending — never on a malformed frame, a different event, or a stale one.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { wireAutoSummary } from "./wire-auto-summary";
import { PROTOCOL_VERSION } from "./protocol";
import { createSettingsStore, type SettingsStore } from "./settings-store";
import { createMeetingFinalizeStore, type MeetingFinalizeStore } from "./meeting-finalize-store";
import { createNotepadStore, type NotepadStore } from "./notepad-store";

const BASE_SETTINGS = {
  vaultDir: null,
  pushToTalkHotkey: ["F9"] as const,
  keepAudio: false,
  disclosureReminder: true,
  killSwitch: false,
  instantExecuteWhitelist: [] as const,
  activeTemplate: "auto",
  customTemplates: [] as const,
  onboardingComplete: true,
  detectionAutoStartSources: [] as const,
  autostopSilenceS: 60,
  liveCaptionsOverlay: true,
  aecEnabled: false,
  liveTranslationLang: "",
  summaryLanguage: "",
  speakerIdentity: "Me",
  speakerVoiceEnrolled: false,
  summaryModelId: "llama3.2",
  ollamaBaseUrl: "http://127.0.0.1:11434",
  dictationCleanupStyle: "none" as const,
  sttEngine: "parakeet" as const,
  sttModelId: "",
  sttOpenaiBaseUrl: "",
  selectionTranslationLang: "English",
  summaryProvider: "ollama" as const,
};

function settingsStoreWith(autoSummary: boolean): SettingsStore {
  const store = createSettingsStore();
  store.setState({
    settings: { ...BASE_SETTINGS, autoSummary },
    settingsPhase: "ready",
    settingsError: null,
    killSwitchEngaged: false,
    routing: [],
    templateOptions: [],
    ledgerPhase: "loading",
    ledgerError: null,
    ledger: null,
    devicesPhase: "pending",
    devicesError: null,
    devices: [],
    devicesSource: "pending",
    selectedInputDeviceId: null,
    selectedOutputDeviceId: null,
  });
  return store;
}

/** A fake frame bus: capture the listener so the test can push raw frames. */
function fakeBus(): { subscribe: (listener: (data: unknown) => void) => () => void; push: (data: unknown) => void; unsubscribeCount: number } {
  let listener: ((data: unknown) => void) | null = null;
  let unsubscribeCount = 0;
  return {
    subscribe: (l) => {
      listener = l;
      return () => {
        unsubscribeCount += 1;
        listener = null;
      };
    },
    push: (data) => listener?.(data),
    get unsubscribeCount() {
      return unsubscribeCount;
    },
  };
}

function captureStoppedFrame(meetingId: string, extra: Record<string, unknown> = {}): unknown {
  return {
    v: PROTOCOL_VERSION,
    kind: "event",
    name: "capture.stopped",
    id: "evt-1",
    payload: { meeting_id: meetingId, reason: "command", ...extra },
  };
}

describe("wireAutoSummary", () => {
  let finalizeStore: MeetingFinalizeStore;
  let notepad: NotepadStore;
  let finalize: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    finalizeStore = createMeetingFinalizeStore();
    notepad = createNotepadStore();
    finalize = vi.fn().mockResolvedValue(undefined);
  });

  it("finalizes with the meeting id, notepad, and active template when autoSummary is on", () => {
    const bus = fakeBus();
    notepad.setState({ meetingId: "m-1", text: "rough notes" });
    const settingsStore = settingsStoreWith(true);
    settingsStore.setState({
      settings: { ...BASE_SETTINGS, autoSummary: true,
      cartesiaVoiceId: "", micDeviceId: "", activeTemplate: "sales" },
    });

    wireAutoSummary(settingsStore, finalizeStore, notepad, bus.subscribe, finalize);
    bus.push(captureStoppedFrame("m-1"));

    expect(finalize).toHaveBeenCalledTimes(1);
    expect(finalize).toHaveBeenCalledWith("m-1", "rough notes", finalizeStore, undefined, "sales");
  });

  it("does nothing when autoSummary is off", () => {
    const bus = fakeBus();
    const settingsStore = settingsStoreWith(false);

    wireAutoSummary(settingsStore, finalizeStore, notepad, bus.subscribe, finalize);
    bus.push(captureStoppedFrame("m-1"));

    expect(finalize).not.toHaveBeenCalled();
  });

  it("does nothing when a finalize flow is already pending", () => {
    const bus = fakeBus();
    finalizeStore.setState({ status: "pending", meetingId: "m-1" });
    const settingsStore = settingsStoreWith(true);

    wireAutoSummary(settingsStore, finalizeStore, notepad, bus.subscribe, finalize);
    bus.push(captureStoppedFrame("m-1"));

    expect(finalize).not.toHaveBeenCalled();
  });

  it("ignores an unrelated event", () => {
    const bus = fakeBus();
    const settingsStore = settingsStoreWith(true);

    wireAutoSummary(settingsStore, finalizeStore, notepad, bus.subscribe, finalize);
    bus.push({
      v: PROTOCOL_VERSION,
      kind: "event",
      name: "capture.started",
      id: "evt-2",
      payload: { meeting_id: "m-1", reason: "command" },
    });

    expect(finalize).not.toHaveBeenCalled();
  });

  it.each<[string, unknown]>([
    ["not an envelope at all", "garbage"],
    ["a reply, not an event", { v: PROTOCOL_VERSION, kind: "reply", name: "capture.stopped", id: "x", payload: {} }],
    ["missing meeting_id", captureStoppedFrame("")],
    ["wrong protocol version", { v: 2, kind: "event", name: "capture.stopped", id: "x", payload: { meeting_id: "m-1", reason: "command" } }],
  ])("fails closed on %s", (_label, frame) => {
    const bus = fakeBus();
    const settingsStore = settingsStoreWith(true);

    wireAutoSummary(settingsStore, finalizeStore, notepad, bus.subscribe, finalize);
    bus.push(frame);

    expect(finalize).not.toHaveBeenCalled();
  });

  it("returns an unsubscribe that detaches from the frame bus", () => {
    const bus = fakeBus();
    const settingsStore = settingsStoreWith(true);

    const unwire = wireAutoSummary(settingsStore, finalizeStore, notepad, bus.subscribe, finalize);
    unwire();
    bus.push(captureStoppedFrame("m-1"));

    expect(bus.unsubscribeCount).toBe(1);
    expect(finalize).not.toHaveBeenCalled();
  });
});
