/**
 * useNaomiConversationControls: translates the user's mic gestures (push-to-talk
 * hold/release, open-mic toggle) into the frozen listen commands on the socket
 * AND the matching reducer dispatches, keeping that gesture→command→state logic
 * in one named place instead of inline in NaomiView.
 *
 * Fail-closed: if a command cannot be sent (engine offline) it dispatches
 * connection-lost rather than pretending the mic opened. Priming the audio
 * graph on the down-gesture satisfies the browser autoplay policy so the reply
 * plays without a stall.
 */

import { useState, type Dispatch, type RefObject } from "react";
import type { NaomiConversationAction } from "./naomi-conversation-store";
import type { NaomiEngineVoiceSocket } from "./naomi-engine-voice-socket";

export interface NaomiConversationControlsParams {
  readonly socketRef: RefObject<NaomiEngineVoiceSocket | null>;
  readonly dispatch: Dispatch<NaomiConversationAction>;
  /** Current open-mic flag from the reducer (decides the toggle direction). */
  readonly openMic: boolean;
  /** Primes the AudioContext on a user gesture (autoplay policy). */
  readonly ensurePlayback: () => void;
}

export interface NaomiConversationControls {
  readonly pushToTalkHeld: boolean;
  readonly onPushToTalkDown: () => void;
  readonly onPushToTalkUp: () => void;
  readonly onToggleOpenMic: () => void;
}

export function useNaomiConversationControls(
  params: NaomiConversationControlsParams,
): NaomiConversationControls {
  const { socketRef, dispatch, openMic, ensurePlayback } = params;
  const [pushToTalkHeld, setPushToTalkHeld] = useState(false);

  // Push-to-talk down: open the mic for a single utterance (open_mic=false).
  const onPushToTalkDown = () => {
    ensurePlayback();
    const sent = socketRef.current?.listenStart(false);
    if (sent !== true) {
      dispatch({ type: "connection-lost" });
      return;
    }
    setPushToTalkHeld(true);
    dispatch({ type: "listen-start", openMic: false });
  };

  // Release flushes the pending speech into the turn (flush=true).
  const onPushToTalkUp = () => {
    if (!pushToTalkHeld) return;
    setPushToTalkHeld(false);
    socketRef.current?.listenStop(true);
    dispatch({ type: "listen-stop" });
  };

  // Open-mic toggle: on = VAD conversation; off discards pending audio (flush=false).
  const onToggleOpenMic = () => {
    ensurePlayback();
    if (openMic) {
      socketRef.current?.listenStop(false);
      dispatch({ type: "listen-stop" });
      return;
    }
    const sent = socketRef.current?.listenStart(true);
    if (sent !== true) {
      dispatch({ type: "connection-lost" });
      return;
    }
    dispatch({ type: "listen-start", openMic: true });
  };

  return { pushToTalkHeld, onPushToTalkDown, onPushToTalkUp, onToggleOpenMic };
}
