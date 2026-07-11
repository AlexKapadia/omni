/**
 * Naomi conversation panel: the REAL turn-loop UI that sits beneath the pool
 * — push-to-talk + open-mic controls, the verbatim You/Naomi captions, the
 * citation chips, the optional debug latency table, and honest error surfacing.
 *
 * Purely presentational: it renders the reduced conversation state and calls
 * back into NaomiView (which owns the socket + reducer). Monochrome, fully
 * design-token styled — no new colors, gradients, or shadows. Nothing here is
 * decorative; every control is wired to a real command.
 */

import type { NaomiConversationState } from "./naomi-conversation-store";
import type { NaomiReplyCitation, NaomiTurnLatencyEvent } from "./naomi-turn-protocol";

export interface NaomiConversationPanelProps {
  readonly state: NaomiConversationState;
  readonly engineConnected: boolean;
  /** true while the push-to-talk button is physically held down. */
  readonly pushToTalkHeld: boolean;
  readonly onPushToTalkDown: () => void;
  readonly onPushToTalkUp: () => void;
  readonly onToggleOpenMic: () => void;
}

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  letterSpacing: "var(--label-ls)",
  textTransform: "uppercase",
  color: "var(--ink-secondary)",
};

const monoStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--text-meta-size)",
  color: "var(--grey-600)",
};

/** Basename of a vault path for a compact chip label (POSIX or Windows sep). */
function noteBasename(notePath: string): string {
  const parts = notePath.split(/[\\/]/);
  return parts[parts.length - 1] || notePath;
}

const LATENCY_ROWS: ReadonlyArray<{ key: keyof NaomiTurnLatencyEvent; label: string }> = [
  { key: "endpoint_ms", label: "Endpoint" },
  { key: "retrieval_ms", label: "Retrieval" },
  { key: "llm_ms", label: "LLM" },
  { key: "ttfa_ms", label: "TTFA" },
  { key: "total_ms", label: "Total" },
];

/**
 * Per-turn latency table is a power-user diagnostic, HIDDEN by default.
 * Opt in with localStorage `omni.naomi.debugLatency = "true"`.
 */
function latencyDebugEnabled(): boolean {
  try {
    return window.localStorage.getItem("omni.naomi.debugLatency") === "true";
  } catch {
    return false;
  }
}

function LatencyTable({ latency }: { readonly latency: NaomiTurnLatencyEvent | null }) {
  if (!latencyDebugEnabled()) return null;
  // Em-dash for every span until a real measurement lands (never a fake 0).
  return (
    <div data-testid="naomi-latency-table">
      <p className="m-0 mb-[var(--space-2)]" style={labelStyle}>
        Latency
      </p>
      <table style={{ ...monoStyle, borderCollapse: "collapse" }}>
        <tbody>
          {LATENCY_ROWS.map((row) => (
            <tr key={row.key}>
              <td style={{ paddingRight: "var(--space-4)", color: "var(--ink-secondary)" }}>
                {row.label}
              </td>
              <td style={{ textAlign: "right", color: "var(--ink)" }}>
                {latency === null ? "—" : `${latency[row.key]} ms`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CitationChips({ citations }: { readonly citations: readonly NaomiReplyCitation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-[var(--space-2)]" data-testid="naomi-citation-chips">
      {citations.map((citation) => (
        <span
          key={`${citation.n}-${citation.note_path}-${citation.line_start}`}
          // title exposes the exact cited quote — provenance the user can inspect.
          title={citation.quote}
          className="inline-flex items-center gap-[var(--space-1)] border border-[var(--grey-200)]"
          style={{
            padding: "2px 8px",
            borderRadius: "var(--radius-chip)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--grey-600)",
          }}
        >
          <span style={{ color: "var(--ink)" }}>[{citation.n}]</span>
          {noteBasename(citation.note_path)}
        </span>
      ))}
    </div>
  );
}

/** One labelled caption line (You / Naomi) — grey mono label, body-font text. */
function TurnCaption({
  speaker,
  text,
  textColor,
}: {
  readonly speaker: string;
  readonly text: string | null;
  readonly textColor: string;
}) {
  if (text === null) return null;
  return (
    <p className="m-0" style={{ fontFamily: "var(--font-body)", fontSize: 15, color: textColor }}>
      <span style={{ ...labelStyle, marginRight: "var(--space-3)" }}>{speaker}</span>
      {text}
    </p>
  );
}

export function NaomiConversationPanel(props: NaomiConversationPanelProps) {
  const { state, engineConnected, pushToTalkHeld } = props;
  const controlsDisabled = !engineConnected;

  return (
    <section
      aria-label="Naomi conversation"
      className="border-t border-[var(--grey-200)] bg-[var(--canvas)]"
      style={{ padding: "16px 48px 20px" }}
    >
      <div className="flex flex-wrap items-start gap-[var(--space-8)]">
        {/* --- Controls: push-to-talk + open-mic conversation toggle --- */}
        <div className="flex flex-col gap-[var(--space-2)]">
          <p className="m-0" style={labelStyle}>
            Talk {engineConnected ? "" : "· engine offline"}
          </p>
          <div className="flex gap-[var(--space-2)]">
            <button
              type="button"
              // Push-to-talk: hold to listen, release to send (flush) the turn.
              onPointerDown={props.onPushToTalkDown}
              onPointerUp={props.onPushToTalkUp}
              onPointerLeave={() => {
                if (pushToTalkHeld) props.onPushToTalkUp();
              }}
              disabled={controlsDisabled}
              aria-pressed={pushToTalkHeld}
              className={
                "cursor-pointer touch-none select-none border bg-transparent " +
                (pushToTalkHeld
                  ? "border-[var(--ink)] font-medium text-[var(--ink)]"
                  : "border-[var(--grey-300)] text-[var(--ink)] hover:border-[var(--ink)]") +
                " disabled:cursor-default disabled:border-[var(--grey-300)] disabled:text-[var(--grey-300)]"
              }
              style={{
                padding: "8px 16px",
                borderRadius: "var(--radius-control)",
                fontSize: 13,
                fontFamily: "var(--font-body)",
              }}
            >
              {pushToTalkHeld ? "Listening…" : "Hold to talk"}
            </button>
            <button
              type="button"
              // Open-mic: VAD-gated conversation; the engine drives every turn.
              onClick={props.onToggleOpenMic}
              disabled={controlsDisabled}
              aria-pressed={state.openMic}
              className={
                "cursor-pointer border bg-transparent " +
                (state.openMic
                  ? "border-[var(--ink)] font-medium text-[var(--ink)]"
                  : "border-[var(--grey-300)] text-[var(--grey-600)] hover:border-[var(--ink)]") +
                " disabled:cursor-default disabled:border-[var(--grey-300)] disabled:text-[var(--grey-300)]"
              }
              style={{
                padding: "8px 16px",
                borderRadius: "var(--radius-control)",
                fontSize: 13,
                fontFamily: "var(--font-body)",
              }}
            >
              {state.openMic ? "Conversation on" : "Conversation off"}
            </button>
          </div>
          <p className="m-0" style={monoStyle} data-testid="naomi-turn-state">
            {state.turnState}
          </p>
        </div>

        {/* --- Turn captions: verbatim You + Naomi's reply --- */}
        <div className="flex min-w-[360px] flex-1 flex-col gap-[var(--space-3)]">
          <TurnCaption speaker="You" text={state.userText} textColor="var(--ink)" />
          <TurnCaption speaker="Naomi" text={state.replyText} textColor="var(--grey-600)" />
          {state.noAnswer && state.replyText !== null && (
            <p className="m-0" style={{ ...monoStyle, color: "var(--ink-secondary)" }}>
              Not found in your notes.
            </p>
          )}
          <CitationChips citations={state.citations} />
          {state.actionCardId !== null && (
            <p className="m-0" style={monoStyle} data-testid="naomi-action-card">
              Action prepared — card #{state.actionCardId} awaits approval.
            </p>
          )}
          {state.error !== null && (
            <p className="m-0" style={{ ...monoStyle, color: "var(--ink)" }} role="alert">
              {state.error}
            </p>
          )}
        </div>

        {/* --- Live latency table (speed showcase) --- */}
        <LatencyTable latency={state.latency} />
      </div>
    </section>
  );
}
