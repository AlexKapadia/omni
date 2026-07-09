/**
 * Hold-to-talk FSM with locked recording (Talkis-style).
 * Release schedules stop; a quick re-press locks; press while locked stops.
 */

export type HotkeyShortcutState = "Pressed" | "Released";

export type HotkeyFsmCommand =
  | "start_recording"
  | "stop_recording"
  | "schedule_stop_after_release"
  | "clear_release_stop_timer"
  | "lock_recording";

export interface HotkeyFsmState {
  recording: boolean;
  hotkeyHeld: boolean;
  lockedRecording: boolean;
  suppressNextRelease: boolean;
  releaseStopTimerActive: boolean;
}

export interface HotkeyFsmResult {
  nextState: HotkeyFsmState;
  commands: readonly HotkeyFsmCommand[];
}

export const INITIAL_HOTKEY_FSM_STATE: HotkeyFsmState = {
  recording: false,
  hotkeyHeld: false,
  lockedRecording: false,
  suppressNextRelease: false,
  releaseStopTimerActive: false,
};

export function evaluateHotkeyFsm(
  state: HotkeyFsmState,
  shortcutState: HotkeyShortcutState,
): HotkeyFsmResult {
  const nextState: HotkeyFsmState = { ...state };
  const commands: HotkeyFsmCommand[] = [];

  if (shortcutState === "Pressed") {
    if (state.lockedRecording && state.recording) {
      nextState.hotkeyHeld = true;
      nextState.suppressNextRelease = true;
      commands.push("stop_recording");
      return { nextState, commands };
    }
    if (state.recording && state.releaseStopTimerActive) {
      nextState.hotkeyHeld = true;
      nextState.lockedRecording = true;
      nextState.releaseStopTimerActive = false;
      commands.push("clear_release_stop_timer", "lock_recording");
      return { nextState, commands };
    }
    if (state.hotkeyHeld || state.recording) {
      return { nextState, commands };
    }
    nextState.hotkeyHeld = true;
    nextState.recording = true;
    nextState.lockedRecording = false;
    commands.push("start_recording");
    return { nextState, commands };
  }

  nextState.hotkeyHeld = false;
  if (state.suppressNextRelease) {
    nextState.suppressNextRelease = false;
    nextState.recording = false;
    nextState.lockedRecording = false;
    return { nextState, commands };
  }
  if (state.recording) {
    if (state.lockedRecording) {
      return { nextState, commands };
    }
    commands.push("schedule_stop_after_release");
    nextState.releaseStopTimerActive = true;
    return { nextState, commands };
  }
  return { nextState, commands };
}
