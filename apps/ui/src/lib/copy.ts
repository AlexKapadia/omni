/**
 * Typed runtime accessor over the copy glossary (apps/ui/copy/glossary.json).
 *
 * WHY: redesign-brief-v2.md §6 makes the glossary the single source of truth
 * for shell strings — components import `copy` instead of hardcoding text, so
 * a rename in one JSON file propagates everywhere (including tests that also
 * import from here, per the brief's "renames propagate" contract).
 *
 * WHERE in the pipeline: consumed by nav-rail.tsx and status-footer.tsx (P1);
 * future Home/command-palette/onboarding screens (P2+) read the same object.
 *
 * The object is deep-frozen so an accidental mutation at a call site throws
 * in development instead of silently corrupting shared UI copy at runtime.
 */
import glossary from "../../copy/glossary.json";

export type Copy = typeof glossary;

/** Readonly<T> is shallow — it would let `copy.nav.library = "x"` compile
 * even though the object is frozen at every level at runtime (see
 * deepFreeze below). DeepReadonly mirrors the runtime guarantee in the type
 * system so a mutation attempt is a compile error, not just a silent no-op. */
type DeepReadonly<T> = T extends object ? { readonly [K in keyof T]: DeepReadonly<T[K]> } : T;

/** Recursively freezes a plain JSON value tree. JSON has no cycles, so a
 * simple recursive walk is safe (no visited-set needed). */
function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value as object)) {
      deepFreeze((value as Record<string, unknown>)[key]);
    }
  }
  return value;
}

/** The frozen, typed glossary. Read-only at every level — see deepFreeze above. */
export const copy: DeepReadonly<Copy> = deepFreeze(glossary);
