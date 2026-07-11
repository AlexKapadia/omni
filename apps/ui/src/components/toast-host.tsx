/**
 * Fixed-bottom toast stack: a few auto-dismissing notices, mounted once at
 * the app root. Each toast also carries a manual dismiss control.
 */
import { useStore } from "zustand";
import { dismissToast, toastStore, type ToastStore } from "../lib/toast-store";

const VARIANT_TEXT_COLOR: Readonly<Record<string, string>> = {
  info: "var(--ink)",
  success: "var(--success-text, var(--ink))",
  error: "var(--error-text)",
};

export function ToastHost({ store = toastStore }: { readonly store?: ToastStore }) {
  const toasts = useStore(store, (s) => s.toasts);

  if (toasts.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2"
      style={{ padding: "var(--space-4)" }}
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className="pointer-events-auto flex items-center gap-3 border border-[var(--grey-200)] bg-[var(--surface)]"
          style={{
            borderRadius: "var(--radius-control)",
            padding: "8px 14px",
            fontSize: 13,
            boxShadow: "var(--shadow-card, 0 4px 16px rgba(0,0,0,0.12))",
            color: VARIANT_TEXT_COLOR[t.variant] ?? "var(--ink)",
          }}
        >
          <span>{t.message}</span>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => dismissToast(t.id, store)}
            className="cursor-pointer text-[var(--ink-secondary)] hover:text-[var(--ink)]"
            style={{ background: "none", border: "none", padding: 0, fontSize: 14, lineHeight: 1 }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
