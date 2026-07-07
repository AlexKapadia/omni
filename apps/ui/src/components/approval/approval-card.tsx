/**
 * One approval card in the post-meeting rack (design §05).
 *
 * Visuals per the components doc: 264px card, grey-200 border, radius 12,
 * padding 18, mono-caps type label, 14px/500 title, mono-12 grey-600 dry-run
 * detail lines, then [Approve primary-small] [Edit ghost] [Dismiss ghost].
 *
 * Honesty invariants: every state renders truthfully — pending shows the
 * exact dry-run preview the engine computed; approved/executing show real
 * progress (buttons gone — the decision is made); executed shows the ✓ chip
 * with the tool's real summary; failed shows the plain-voice error and a
 * Retry. Status arrives ONLY from engine events (store invariant) — nothing
 * here flips a card optimistically.
 */
import { useState } from "react";
import {
  approveCard,
  dismissCard,
  retryCard,
  CARD_TYPE_LABELS,
  type ApprovalCard as ApprovalCardData,
} from "../../lib/approval-cards-store";
import { OmniButton } from "../button";
import { ApprovalCardEditFields } from "./approval-card-edit-fields";

interface ApprovalCardProps {
  readonly card: ApprovalCardData;
  /** True while a decision on this card is in flight (buttons disable). */
  readonly inFlight: boolean;
}

const CARD_FRAME: React.CSSProperties = {
  width: 264,
  border: "1px solid var(--grey-200)",
  borderRadius: 12,
  padding: 18,
  display: "flex",
  flexDirection: "column",
  gap: 10,
  background: "var(--canvas)",
};

const MONO_LABEL: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  letterSpacing: "var(--label-ls)",
  textTransform: "uppercase",
  color: "var(--ink-secondary)",
  margin: 0,
};

const DETAIL_LINE: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  color: "var(--grey-600)",
  margin: 0,
  overflowWrap: "anywhere",
};

/** The ink chip shown once the action really happened (design §05). */
function ApprovedChip({ text }: { readonly text: string }) {
  return (
    <span
      style={{
        background: "var(--ink)",
        color: "var(--canvas)",
        borderRadius: 999,
        padding: "8px 16px",
        fontSize: 13,
        fontWeight: 500,
        alignSelf: "flex-start",
      }}
    >
      ✓ {text}
    </span>
  );
}

export function ApprovalCard({ card, inFlight }: ApprovalCardProps) {
  const [editing, setEditing] = useState(false);
  if (card.status === "dismissed") {
    return null; // dismissed cards leave the rack; the engine remembers them
  }
  const title =
    typeof card.payload["title"] === "string"
      ? (card.payload["title"] as string)
      : typeof card.payload["name"] === "string"
        ? (card.payload["name"] as string)
        : typeof card.payload["subject"] === "string"
          ? (card.payload["subject"] as string)
          : CARD_TYPE_LABELS[card.cardType];

  return (
    <article style={CARD_FRAME} aria-label={`${CARD_TYPE_LABELS[card.cardType]} card`}>
      <p style={MONO_LABEL}>{CARD_TYPE_LABELS[card.cardType]}</p>
      <h3 style={{ fontSize: 14, fontWeight: 500, color: "var(--ink)", margin: 0 }}>{title}</h3>

      {card.status === "pending" && !editing && (
        <>
          {card.previewLines.map((line) => (
            <p key={line} style={DETAIL_LINE}>
              {line}
            </p>
          ))}
          <div style={{ display: "flex", gap: 4 }}>
            <OmniButton
              variant="primary"
              small
              disabled={inFlight}
              onClick={() => approveCard(card.id)}
            >
              Approve
            </OmniButton>
            <OmniButton
              variant="ghost"
              small
              disabled={inFlight}
              onClick={() => setEditing(true)}
            >
              Edit
            </OmniButton>
            <OmniButton
              variant="ghost-dismiss"
              small
              disabled={inFlight}
              onClick={() => dismissCard(card.id)}
            >
              Dismiss
            </OmniButton>
          </div>
        </>
      )}

      {card.status === "pending" && editing && (
        <ApprovalCardEditFields
          payload={card.payload}
          onSave={(edited) => {
            setEditing(false);
            // Edit + approve are ONE command: the engine locks the payload
            // at the decision, so what you saved is exactly what executes.
            approveCard(card.id, edited);
          }}
          onCancel={() => setEditing(false)}
        />
      )}

      {(card.status === "approved" || card.status === "executing") && (
        <p style={DETAIL_LINE} role="status">
          {card.status === "approved" ? "Approved — starting…" : "Working…"}
        </p>
      )}

      {card.status === "executed" && (
        <ApprovedChip text={card.resultSummary ?? "Done"} />
      )}

      {card.status === "failed" && (
        <>
          <p style={{ ...DETAIL_LINE, color: "var(--ink)" }} role="alert">
            {card.error ?? "This action failed."}
          </p>
          <div style={{ display: "flex", gap: 4 }}>
            <OmniButton
              variant="secondary"
              small
              disabled={inFlight}
              onClick={() => retryCard(card.id)}
            >
              Retry
            </OmniButton>
          </div>
        </>
      )}
    </article>
  );
}
