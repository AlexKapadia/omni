/**
 * Zustand store holding the engine connection status the UI renders.
 *
 * Written only by engine-connection.ts; read by the status footer (and any
 * future screen that needs engine liveness). Kept as a factory so tests can
 * create isolated stores instead of sharing mutable module state.
 */
import { createStore, useStore, type StoreApi } from "zustand";

export type EngineStatus = "connecting" | "connected" | "disconnected";

export interface EngineStatusState {
  readonly status: EngineStatus;
  /** Seconds the engine has been up, from the last heartbeat. Null until first heartbeat. */
  readonly uptimeS: number | null;
  /** Engine semver from the last heartbeat. Null until first heartbeat. */
  readonly engineVersion: string | null;
  /** Last ping→pong round trip in ms. Null until first successful ping. */
  readonly lastLatencyMs: number | null;
  /** Whether the on-device STT model is loaded, from the last heartbeat. */
  readonly sttReady: boolean;
  readonly sttEngine: string | null;
  readonly sttDevice: string | null;
}

export const INITIAL_ENGINE_STATUS: EngineStatusState = {
  status: "connecting",
  uptimeS: null,
  engineVersion: null,
  lastLatencyMs: null,
  sttReady: false,
  sttEngine: null,
  sttDevice: null,
};

export type EngineStatusStore = StoreApi<EngineStatusState>;

export function createEngineStatusStore(): EngineStatusStore {
  return createStore<EngineStatusState>(() => INITIAL_ENGINE_STATUS);
}

/** The one store the running app uses. Tests create their own via the factory. */
export const engineStatusStore: EngineStatusStore = createEngineStatusStore();

/** React hook over the app singleton store. */
export function useEngineStatus<T>(selector: (state: EngineStatusState) => T): T {
  return useStore(engineStatusStore, selector);
}
