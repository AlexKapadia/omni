/**
 * Behaviour tests for lib/copy.ts: it must be the exact glossary content
 * (renames-propagate contract, redesign-brief-v2.md §6), deeply frozen
 * (read-only at every level, not just the top object), and must carry the
 * keys nav-rail.tsx / status-footer.tsx actually consume.
 */
import { describe, expect, it } from "vitest";
import { copy } from "./copy";
import glossary from "../../copy/glossary.json";

describe("copy module matches the glossary exactly", () => {
  it("is deep-equal to the raw glossary JSON", () => {
    expect(copy).toEqual(glossary);
  });

  it("carries every nav label nav-rail.tsx renders", () => {
    expect(copy.nav.library).toBe("Meetings");
    expect(copy.nav.live).toBe("Record");
    expect(copy.nav.ask).toBe("Ask");
    expect(copy.nav.dictation).toBe("Voice notes");
    expect(copy.nav.naomi).toBe("Naomi");
    expect(copy.nav.settings).toBe("Settings");
    expect(copy.nav.trustLine).toBe("Your data stays on this device");
  });

  it("carries the new P2-reserved home/record keys additively", () => {
    expect(copy.nav.home).toBe("Home");
    expect(copy.nav.record).toBe("Record");
  });

  it("carries every engineStatus label status-footer.tsx renders", () => {
    expect(copy.engineStatus.connecting).toBe("Starting…");
    expect(copy.engineStatus.connected).toBe("Ready");
    expect(copy.engineStatus.disconnected).toBe("Omni Steroid isn’t running");
  });

  it("carries the common actions used by the new primitives (e.g. Coachmark's Got it button)", () => {
    expect(copy.common.gotIt).toBe("Got it");
  });
});

describe("copy module is frozen at every level", () => {
  it("is frozen at the top level", () => {
    expect(Object.isFrozen(copy)).toBe(true);
  });

  it("is frozen on nested objects (nav, engineStatus, common, jargonReplacements)", () => {
    expect(Object.isFrozen(copy.nav)).toBe(true);
    expect(Object.isFrozen(copy.engineStatus)).toBe(true);
    expect(Object.isFrozen(copy.common)).toBe(true);
    expect(Object.isFrozen(copy.jargonReplacements)).toBe(true);
  });

  it("silently refuses a mutation attempt in non-strict runtime code (value is unchanged)", () => {
    const before = copy.nav.library;
    try {
      // @ts-expect-error -- deliberately violating readonly-ness to prove the runtime freeze holds even if a caller bypasses the type system
      copy.nav.library = "Tampered";
    } catch {
      // Some environments throw in strict mode instead of silently failing —
      // either outcome is acceptable; only an actual mutation is a failure.
    }
    expect(copy.nav.library).toBe(before);
  });
});
