/**
 * Settings — the two-tier segmented control (Essentials | Advanced).
 *
 * A small, reusable ARIA tablist: each tab is role="tab" with aria-selected and
 * roving tabindex; Arrow/Home/End move focus AND selection (single-select
 * pattern). The selected tab wears the --accent-muted wash with --ink text;
 * keyboard focus is the --focus-ring outline. Token-driven, no raw hex.
 */
import { useRef } from "react";

export interface TierTab {
  readonly id: string;
  readonly label: string;
}

export function SettingsTierTabs({
  tabs,
  active,
  onChange,
  idBase = "settings-tier",
  ariaLabel = "Settings sections",
}: {
  readonly tabs: readonly TierTab[];
  readonly active: string;
  readonly onChange: (id: string) => void;
  readonly idBase?: string;
  readonly ariaLabel?: string;
}) {
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const focusTab = (index: number): void => {
    const clamped = (index + tabs.length) % tabs.length;
    const tab = tabs[clamped];
    if (tab === undefined) return;
    onChange(tab.id);
    buttonRefs.current[clamped]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent, index: number): void => {
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        focusTab(index + 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        focusTab(index - 1);
        break;
      case "Home":
        event.preventDefault();
        focusTab(0);
        break;
      case "End":
        event.preventDefault();
        focusTab(tabs.length - 1);
        break;
      default:
        break;
    }
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="flex gap-[var(--space-6)] border-b border-solid border-[var(--grey-200)] w-full"
      style={{
        paddingBottom: 0,
      }}
    >
      {tabs.map((tab, index) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            ref={(element) => {
              buttonRefs.current[index] = element;
            }}
            type="button"
            role="tab"
            id={`${idBase}-tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`${idBase}-panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`relative cursor-pointer border-none bg-transparent font-[family-name:var(--font-label)] font-semibold transition-colors duration-[var(--dur-micro)] pb-[var(--space-3)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] ${
              selected
                ? "text-[var(--ink)]"
                : "text-[var(--ink-secondary)] hover:text-[var(--ink)]"
            }`}
            style={{
              fontSize: 14,
              lineHeight: 1.4,
            }}
          >
            {tab.label}
            {selected && (
              <span
                style={{
                  position: "absolute",
                  bottom: -1,
                  left: 0,
                  right: 0,
                  height: 2,
                  background: "var(--accent)",
                  borderRadius: 0,
                }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
