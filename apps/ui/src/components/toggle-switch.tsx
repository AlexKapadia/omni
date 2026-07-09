/**
 * The design-system toggle: 36x20 pill track, 16px white knob inset 2px.
 * On: ink track, knob right. Off: grey-200 track, knob left with the knob
 * shadow. Knob travel uses the --dur-toggle token (120ms).
 *
 * Accessible switch semantics: role="switch" + aria-checked + a real label,
 * state never conveyed by position alone.
 */
export function ToggleSwitch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  readonly checked: boolean;
  readonly onChange: (next: boolean) => void;
  readonly label: string;
  readonly disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="relative shrink-0 cursor-pointer border-none disabled:cursor-default disabled:opacity-50 disabled:cursor-not-allowed outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)] focus-visible:outline-offset-2 focus-visible:rounded-full"
      style={{
        width: 36,
        height: 20,
        borderRadius: "var(--radius-pill)",
        background: checked ? "var(--accent)" : "var(--grey-300)",
        transition: "background var(--dur-toggle) var(--ease-out)",
        padding: 0,
      }}
    >
      <span
        aria-hidden
        style={{
          position: "absolute",
          top: 2,
          left: 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "var(--canvas)",
          boxShadow: "var(--shadow-knob)",
          transform: checked ? "translateX(16px)" : "translateX(0)",
          transition: "transform var(--dur-toggle) var(--ease-out)",
        }}
      />
    </button>
  );
}
