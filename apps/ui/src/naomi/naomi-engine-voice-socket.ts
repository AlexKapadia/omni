/**
 * Naomi's own engine socket: a second WebSocket to the engine's /ws endpoint
 * dedicated to the voice dev loop (naomi.say / naomi.cancel out; audio
 * chunk / done / timestamps events in).
 *
 * WHY a separate socket instead of teeing lib/live-engine-socket.ts: the
 * engine's EventBroadcastHub fans every event out to EVERY connected socket,
 * so a dedicated connection gets the voice events with ZERO changes to the
 * shared capture wiring (other agents own that file's content — smallest
 * possible footprint outside apps/ui/src/naomi/).
 *
 * Security invariant: inbound frames are untrusted — parsed fail-closed via
 * lib/protocol.ts then the naomi-voice-protocol payload parsers; anything
 * malformed is dropped, never partially applied.
 */

import { ENGINE_WS_URL, makeCommand, parseInboundMessage } from "../lib/protocol";
import {
  NAOMI_AUDIO_CHUNK_EVENT_NAME,
  NAOMI_AUDIO_DONE_EVENT_NAME,
  NAOMI_CANCEL_COMMAND_NAME,
  NAOMI_SAY_COMMAND_NAME,
  NAOMI_SPEAKING_TIMESTAMPS_EVENT_NAME,
  buildNaomiSayPayload,
  parseNaomiAudioChunkPayload,
  parseNaomiAudioDonePayload,
  parseNaomiSpeakingTimestampsPayload,
  type NaomiAudioChunkPayload,
  type NaomiAudioDonePayload,
  type NaomiSayAffect,
  type NaomiSpeakingTimestampsPayload,
} from "./naomi-voice-protocol";

export interface NaomiVoiceEventHandlers {
  readonly onAudioChunk: (chunk: NaomiAudioChunkPayload) => void;
  readonly onAudioDone: (done: NaomiAudioDonePayload) => void;
  readonly onTimestamps: (stamps: NaomiSpeakingTimestampsPayload) => void;
  /** Structured engine refusals (kill switch, missing key) — shown honestly. */
  readonly onErrorReply: (message: string) => void;
  readonly onConnectionChange: (connected: boolean) => void;
}

/** Route one raw frame to the handlers. Exported for direct unit testing. */
export function dispatchNaomiVoiceFrame(raw: unknown, handlers: NaomiVoiceEventHandlers): void {
  const result = parseInboundMessage(raw);
  if (!result.ok) return; // fail closed on malformed frames
  const { kind, name, payload } = result.envelope;
  if (kind === "reply" && name === "error") {
    const message = payload["message"];
    handlers.onErrorReply(typeof message === "string" ? message : "engine refused the command");
    return;
  }
  if (kind !== "event") return;
  if (name === NAOMI_AUDIO_CHUNK_EVENT_NAME) {
    const parsed = parseNaomiAudioChunkPayload(payload);
    if (parsed !== null) handlers.onAudioChunk(parsed);
  } else if (name === NAOMI_AUDIO_DONE_EVENT_NAME) {
    const parsed = parseNaomiAudioDonePayload(payload);
    if (parsed !== null) handlers.onAudioDone(parsed);
  } else if (name === NAOMI_SPEAKING_TIMESTAMPS_EVENT_NAME) {
    const parsed = parseNaomiSpeakingTimestampsPayload(payload);
    if (parsed !== null) handlers.onTimestamps(parsed);
  }
  // Heartbeats and capture events on this socket are deliberately ignored.
}

export class NaomiEngineVoiceSocket {
  private socket: WebSocket | null = null;
  private readonly handlers: NaomiVoiceEventHandlers;
  private closedByUs = false;

  constructor(handlers: NaomiVoiceEventHandlers) {
    this.handlers = handlers;
  }

  connect(): void {
    if (this.socket !== null) return; // idempotent under StrictMode
    this.closedByUs = false;
    const socket = new WebSocket(ENGINE_WS_URL);
    this.socket = socket;
    socket.onopen = () => this.handlers.onConnectionChange(true);
    socket.onmessage = (event) => dispatchNaomiVoiceFrame(event.data, this.handlers);
    socket.onclose = () => {
      this.handlers.onConnectionChange(false);
      this.socket = null;
      // Gentle auto-reconnect while the view is mounted; the dev loop needs
      // no backoff sophistication — the engine is local.
      if (!this.closedByUs) setTimeout(() => this.connect(), 2000);
    };
    socket.onerror = () => socket.close();
  }

  disconnect(): void {
    this.closedByUs = true;
    this.socket?.close();
    this.socket = null;
  }

  private send(name: string, payload: Record<string, unknown>): boolean {
    if (this.socket === null || this.socket.readyState !== WebSocket.OPEN) return false;
    try {
      this.socket.send(JSON.stringify(makeCommand(name, payload)));
      return true;
    } catch {
      return false; // fail closed: a torn socket refuses, never throws up-stack
    }
  }

  /** Ask the engine to speak. Returns false when the engine is offline. */
  say(text: string, affect: NaomiSayAffect | null): boolean {
    return this.send(NAOMI_SAY_COMMAND_NAME, buildNaomiSayPayload(text, affect));
  }

  /** Cancel the current utterance (the barge-in wire primitive). */
  cancel(): boolean {
    return this.send(NAOMI_CANCEL_COMMAND_NAME, {});
  }
}
