/**
 * The pill window's wiring: Tauri hold events + its own engine WebSocket.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

import { EngineConnection, type WebSocketLike } from "../lib/engine-connection";
import { makeCommand, parseInboundMessage } from "../lib/protocol";
import {
  evaluateHotkeyFsm,
  INITIAL_HOTKEY_FSM_STATE,
  type HotkeyFsmCommand,
  type HotkeyFsmState,
} from "./dictation-hotkey-fsm";
import {
  DICTATION_BEGIN_COMMAND_NAME,
  DICTATION_END_COMMAND_NAME,
  DICTATION_ERROR_EVENT_NAME,
  DICTATION_FINAL_EVENT_NAME,
  DICTATION_PARTIAL_EVENT_NAME,
  parseDictationErrorPayload,
  parseDictationFinalPayload,
  parseDictationPartialPayload,
} from "./dictation-events-protocol";
import type { DictationPillState } from "./dictation-pill-state";
import { dispatchPillEvent, type DictationPillStore } from "./dictation-pill-store";

export const HOLD_PRESSED_TAURI_EVENT = "dictation-hold-pressed";
export const HOLD_RELEASED_TAURI_EVENT = "dictation-hold-released";

export interface HoldPressedPayload {
  readonly inject_eligible: boolean;
  readonly target_hwnd: number;
}

interface InjectionOutcome {
  readonly ok: boolean;
  readonly elapsed_ms: number;
  readonly failure_reason: string | null;
}

interface ActiveSession {
  readonly targetHwnd: number;
}

const RELEASE_STOP_MS = 180;

export function parseHoldPressedPayload(payload: unknown): HoldPressedPayload {
  if (typeof payload === "object" && payload !== null) {
    const record = payload as Record<string, unknown>;
    const eligible = record["inject_eligible"];
    const hwnd = record["target_hwnd"];
    if (typeof eligible === "boolean" && typeof hwnd === "number" && Number.isFinite(hwnd)) {
      return { inject_eligible: eligible, target_hwnd: hwnd };
    }
  }
  return { inject_eligible: false, target_hwnd: 0 };
}

/** Snapshot inject disposition before the reducer leaves `listening`. */
export function resolveInjectRequested(state: DictationPillState): boolean {
  if (state.phase !== "listening" && state.phase !== "processing") return false;
  return state.injectArmed && !state.commandDetected;
}

export function createDictationEventDispatcher(
  store: DictationPillStore,
  performInjection: (text: string, targetHwnd: number) => Promise<InjectionOutcome> =
    invokeInjection,
  getActiveSession: () => ActiveSession | null = () => activeSession,
): (data: unknown) => void {
  return (data: unknown) => {
    const result = parseInboundMessage(data);
    if (!result.ok || result.envelope.kind !== "event") return;
    const { name, payload } = result.envelope;
    if (name === DICTATION_PARTIAL_EVENT_NAME) {
      const parsed = parseDictationPartialPayload(payload);
      if (parsed !== null) dispatchPillEvent(store, { type: "partial", text: parsed.text });
    } else if (name === DICTATION_FINAL_EVENT_NAME) {
      const parsed = parseDictationFinalPayload(payload);
      if (parsed === null) return;
      const totalMs = releasedAtMs !== null ? Date.now() - releasedAtMs : undefined;
      dispatchPillEvent(store, { type: "final", payload: parsed, totalMs });
      if (parsed.mode === "inject") {
        const textToInject = parsed.cleaned_text ?? parsed.text;
        const target = getActiveSession()?.targetHwnd ?? 0;
        void performInjection(textToInject, target)
          .then((outcome) => {
            dispatchPillEvent(store, {
              type: "injection-result",
              ok: outcome.ok,
              elapsedMs: outcome.elapsed_ms,
              reason: outcome.failure_reason ?? undefined,
            });
          })
          .catch((error: unknown) => {
            dispatchPillEvent(store, {
              type: "injection-result",
              ok: false,
              reason: `insert failed: ${String(error)}`,
            });
          });
      }
      activeSession = null;
    } else if (name === DICTATION_ERROR_EVENT_NAME) {
      const parsed = parseDictationErrorPayload(payload);
      if (parsed !== null) dispatchPillEvent(store, { type: "error", reason: parsed.reason });
      activeSession = null;
    }
  };
}

function invokeInjection(text: string, targetHwnd: number): Promise<InjectionOutcome> {
  return invoke<InjectionOutcome>("inject_dictation_text", { text, targetHwnd });
}

let activeSocket: WebSocket | null = null;
let pillConnection: EngineConnection | null = null;
let activeSession: ActiveSession | null = null;
let releasedAtMs: number | null = null;
let hotkeyFsm: HotkeyFsmState = INITIAL_HOTKEY_FSM_STATE;
let releaseStopTimer: ReturnType<typeof setTimeout> | null = null;
let injectEligibleAtPress = false;
let sessionTargetHwnd = 0;

function clearReleaseStopTimer(): void {
  if (releaseStopTimer !== null) {
    clearTimeout(releaseStopTimer);
    releaseStopTimer = null;
  }
}

function sendDictationCommand(name: string, payload: Record<string, unknown> = {}): boolean {
  if (activeSocket === null || activeSocket.readyState !== WebSocket.OPEN) return false;
  try {
    activeSocket.send(JSON.stringify(makeCommand(name, payload)));
    return true;
  } catch {
    return false;
  }
}

function endSession(
  store: DictationPillStore,
  injectRequested: boolean,
  resetFsm: boolean,
): void {
  releasedAtMs = Date.now();
  dispatchPillEvent(store, { type: "hold-released" });
  if (
    !sendDictationCommand(DICTATION_END_COMMAND_NAME, {
      inject_requested: injectRequested,
    })
  ) {
    dispatchPillEvent(store, {
      type: "error",
      reason: "Engine connection lost — dictation was not saved",
    });
    activeSession = null;
  }
  if (resetFsm) hotkeyFsm = INITIAL_HOTKEY_FSM_STATE;
}

function runHotkeyCommands(store: DictationPillStore, commands: readonly HotkeyFsmCommand[]): void {
  for (const command of commands) {
    if (command === "start_recording") {
      sessionTargetHwnd = injectEligibleAtPress ? sessionTargetHwnd : 0;
      activeSession = { targetHwnd: sessionTargetHwnd };
      dispatchPillEvent(store, {
        type: "hold-pressed",
        atMs: Date.now(),
        injectEligible: injectEligibleAtPress,
      });
      if (!sendDictationCommand(DICTATION_BEGIN_COMMAND_NAME)) {
        activeSession = null;
        hotkeyFsm = INITIAL_HOTKEY_FSM_STATE;
        dispatchPillEvent(store, {
          type: "error",
          reason: "Engine offline — dictation is unavailable",
        });
      }
    } else if (command === "schedule_stop_after_release") {
      const injectRequested = resolveInjectRequested(store.getState());
      clearReleaseStopTimer();
      releaseStopTimer = setTimeout(() => {
        releaseStopTimer = null;
        hotkeyFsm = { ...hotkeyFsm, releaseStopTimerActive: false, recording: false };
        endSession(store, injectRequested, false);
      }, RELEASE_STOP_MS);
    } else if (command === "clear_release_stop_timer") {
      clearReleaseStopTimer();
      hotkeyFsm = { ...hotkeyFsm, releaseStopTimerActive: false };
    } else if (command === "lock_recording") {
      dispatchPillEvent(store, { type: "lock-engaged" });
    } else if (command === "stop_recording") {
      const injectRequested = resolveInjectRequested(store.getState());
      clearReleaseStopTimer();
      endSession(store, injectRequested, true);
    }
  }
}

export function startDictationPillBridge(store: DictationPillStore): () => void {
  if (pillConnection === null) {
    const dispatch = createDictationEventDispatcher(store);
    pillConnection = new EngineConnection({
      createSocket: (url) => createTeeSocket(url, dispatch),
    });
  }
  pillConnection.start();

  const unlisteners: Array<() => void> = [];
  void listen(HOLD_PRESSED_TAURI_EVENT, (event) => {
    const pressed = parseHoldPressedPayload(event.payload);
    sessionTargetHwnd = pressed.target_hwnd;
    injectEligibleAtPress = pressed.inject_eligible;
    const result = evaluateHotkeyFsm(hotkeyFsm, "Pressed");
    hotkeyFsm = result.nextState;
    runHotkeyCommands(store, result.commands);
  }).then((unlisten) => unlisteners.push(unlisten));
  void listen(HOLD_RELEASED_TAURI_EVENT, () => {
    const result = evaluateHotkeyFsm(hotkeyFsm, "Released");
    hotkeyFsm = result.nextState;
    runHotkeyCommands(store, result.commands);
  }).then((unlisten) => unlisteners.push(unlisten));

  return () => {
    clearReleaseStopTimer();
    for (const unlisten of unlisteners) unlisten();
    hotkeyFsm = INITIAL_HOTKEY_FSM_STATE;
    activeSession = null;
    sessionTargetHwnd = 0;
    releasedAtMs = null;
  };
}

function createTeeSocket(url: string, onFrame: (data: unknown) => void): WebSocketLike {
  const inner = new WebSocket(url);
  const tee: WebSocketLike = {
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    send: (data: string) => inner.send(data),
    close: () => inner.close(),
  };
  inner.onopen = () => {
    activeSocket = inner;
    tee.onopen?.();
  };
  inner.onmessage = (event) => {
    onFrame(event.data);
    tee.onmessage?.({ data: event.data });
  };
  inner.onclose = () => {
    if (activeSocket === inner) activeSocket = null;
    tee.onclose?.();
  };
  inner.onerror = () => {
    if (activeSocket === inner) activeSocket = null;
    tee.onerror?.();
  };
  return tee;
}
