/**
 * The post-meeting approval rack (design §05): the row of action cards the
 * engine suggested, each waiting for the user's explicit decision.
 *
 * States are all honest: loading (list not yet replied), empty ("nothing to
 * approve" — a real answer, not a blank), the cards themselves (every status
 * rendered by ApprovalCard), and the engine-offline error from the store.
 */
import { useEffect } from "react";
import {
  requestCardsList,
  useApprovalCards,
} from "../../lib/approval-cards-store";
import { ApprovalCard } from "./approval-card";

const META_TEXT: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  color: "var(--ink-secondary)",
  margin: 0,
};

export function ApprovalRack({
  meetingId,
}: {
  /** When set, only this meeting's cards show (the Library detail mount). */
  readonly meetingId?: string;
} = {}) {
  const cards = useApprovalCards((state) => state.cards);
  const loaded = useApprovalCards((state) => state.loaded);
  const inFlightIds = useApprovalCards((state) => state.inFlightIds);
  const errorMessage = useApprovalCards((state) => state.errorMessage);

  useEffect(() => {
    requestCardsList();
  }, []);

  const visible = cards.filter(
    (card) =>
      card.status !== "dismissed" &&
      (meetingId === undefined || card.meetingId === meetingId),
  );

  return (
    <section aria-label="Approval cards" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {errorMessage !== null && (
        <p role="alert" style={{ ...META_TEXT, color: "var(--grey-600)" }}>
          {errorMessage}
        </p>
      )}
      {errorMessage === null && !loaded && <p style={META_TEXT}>Loading cards…</p>}
      {errorMessage === null && loaded && visible.length === 0 && (
        <p style={META_TEXT}>Nothing to approve.</p>
      )}
      {visible.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {visible.map((card) => (
            <ApprovalCard
              key={card.id}
              card={card}
              inFlight={inFlightIds.includes(card.id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
