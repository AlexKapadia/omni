import { describe, expect, it } from "vitest";
import {
  evaluateHotkeyFsm,
  INITIAL_HOTKEY_FSM_STATE,
} from "./dictation-hotkey-fsm";

describe("evaluateHotkeyFsm", () => {
  it("starts recording on first press", () => {
    const result = evaluateHotkeyFsm(INITIAL_HOTKEY_FSM_STATE, "Pressed");
    expect(result.commands).toEqual(["start_recording"]);
    expect(result.nextState.recording).toBe(true);
  });

  it("schedules stop on release after a normal hold", () => {
    const pressed = evaluateHotkeyFsm(INITIAL_HOTKEY_FSM_STATE, "Pressed");
    const released = evaluateHotkeyFsm(pressed.nextState, "Released");
    expect(released.commands).toEqual(["schedule_stop_after_release"]);
    expect(released.nextState.releaseStopTimerActive).toBe(true);
  });

  it("locks when re-pressed before stop timer fires", () => {
    const pressed = evaluateHotkeyFsm(INITIAL_HOTKEY_FSM_STATE, "Pressed");
    const released = evaluateHotkeyFsm(pressed.nextState, "Released");
    const repressed = evaluateHotkeyFsm(released.nextState, "Pressed");
    expect(repressed.commands).toEqual(["clear_release_stop_timer", "lock_recording"]);
    expect(repressed.nextState.lockedRecording).toBe(true);
  });

  it("ignores release while locked", () => {
    const pressed = evaluateHotkeyFsm(INITIAL_HOTKEY_FSM_STATE, "Pressed");
    const released = evaluateHotkeyFsm(pressed.nextState, "Released");
    const locked = evaluateHotkeyFsm(released.nextState, "Pressed");
    const releaseWhileLocked = evaluateHotkeyFsm(locked.nextState, "Released");
    expect(releaseWhileLocked.commands).toEqual([]);
    expect(releaseWhileLocked.nextState.recording).toBe(true);
  });

  it("stops when pressed again while locked", () => {
    const pressed = evaluateHotkeyFsm(INITIAL_HOTKEY_FSM_STATE, "Pressed");
    const released = evaluateHotkeyFsm(pressed.nextState, "Released");
    const locked = evaluateHotkeyFsm(released.nextState, "Pressed");
    const stop = evaluateHotkeyFsm(locked.nextState, "Pressed");
    expect(stop.commands).toEqual(["stop_recording"]);
  });
});
