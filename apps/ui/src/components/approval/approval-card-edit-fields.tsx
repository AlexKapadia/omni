/**
 * Inline pre-approval editing for one approval card (design §05 "Edit").
 *
 * Every string field of the card payload becomes a text input; Save hands
 * the edited payload UP to the card (which sends it WITH card.approve —
 * the engine schema locks the payload after the decision, so the edit and
 * the approval are one atomic statement). Non-string fields (lists,
 * booleans) are shown read-only here — structured editing is not worth a
 * half-honest coercion UI.
 */
import { useState } from "react";
import { OmniButton } from "../button";

interface ApprovalCardEditFieldsProps {
  readonly payload: Readonly<Record<string, unknown>>;
  readonly onSave: (editedPayload: Record<string, unknown>) => void;
  readonly onCancel: () => void;
}

export function ApprovalCardEditFields({
  payload,
  onSave,
  onCancel,
}: ApprovalCardEditFieldsProps) {
  const stringKeys = Object.keys(payload).filter((key) => typeof payload[key] === "string");
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(stringKeys.map((key) => [key, String(payload[key])])),
  );

  return (
    <form
      style={{ display: "flex", flexDirection: "column", gap: 8 }}
      onSubmit={(event) => {
        event.preventDefault();
        // Merge: edited strings over the original payload — untouched
        // non-string fields ride along unchanged.
        onSave({ ...payload, ...draft });
      }}
    >
      {stringKeys.length === 0 ? (
        <p
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--grey-400)",
            margin: 0,
          }}
        >
          Nothing editable on this card.
        </p>
      ) : (
        stringKeys.map((key) => (
          <label
            key={key}
            style={{ display: "flex", flexDirection: "column", gap: 2 }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                letterSpacing: "var(--label-ls)",
                textTransform: "uppercase",
                color: "var(--grey-400)",
              }}
            >
              {key.replaceAll("_", " ")}
            </span>
            <input
              type="text"
              value={draft[key] ?? ""}
              onChange={(event) =>
                setDraft((current) => ({ ...current, [key]: event.target.value }))
              }
              style={{
                fontFamily: "var(--font-body)",
                fontSize: 13,
                color: "var(--ink)",
                background: "var(--canvas)",
                border: "1px solid var(--grey-300)",
                borderRadius: "var(--radius-control)",
                padding: "6px 8px",
              }}
            />
          </label>
        ))
      )}
      <div style={{ display: "flex", gap: 4 }}>
        <OmniButton variant="primary" small type="submit">
          Save and approve
        </OmniButton>
        <OmniButton variant="ghost" small onClick={onCancel}>
          Cancel
        </OmniButton>
      </div>
    </form>
  );
}
