/**
 * TS mirror of the engine's mode splitter — this table is a SUBSET of the
 * Python decision table in tests/test_dictation__mode_split_fuzzy_prefix_table.py
 * so the two implementations provably agree on every shared case. The
 * engine is authoritative; the pill only flips a chip.
 */
import { describe, expect, it } from "vitest";

import { detectOmniCommandPrefix } from "./omni-command-prefix-detector";

const COMMANDS: string[] = [
  "Omni, schedule lunch with Tom",
  "omni, schedule lunch",
  "OMNI, SCHEDULE LUNCH",
  "Omni schedule lunch",
  "Omni. schedule lunch",
  "Omni: draft an email to dana",
  "Omni; remember this",
  "Omni — create an event",
  "Omni- create an event",
  "  Omni, indented start",
  '"Omni, quoted wake"',
  "...Omni, ellipsis lead-in",
  "Omni,schedule lunch",
  "Ómni, schedule lunch",
  "ÖMNI, schedule lunch",
  "Omni",
  "Omni,",
  "omni   ",
];

const NOTES: string[] = [
  "omnibus schedules are confusing",
  "Omniscient narrators are fun",
  "omni2 is a version number",
  "omni-channel strategy thoughts",
  "Omni-first design notes",
  "The omni channel strategy",
  "remember to buy milk",
  "schedule lunch with Omni",
  "",
  "   ",
  ",,,",
  "\n\t",
  "😀 omni, emoji first word is not the wake word",
];

describe("detectOmniCommandPrefix — mirrors the engine splitter", () => {
  it.each(COMMANDS)("command: %j", (text) => {
    expect(detectOmniCommandPrefix(text)).toBe(true);
  });

  it.each(NOTES)("note: %j", (text) => {
    expect(detectOmniCommandPrefix(text)).toBe(false);
  });

  it("is deterministic", () => {
    for (const text of [...COMMANDS, ...NOTES]) {
      expect(detectOmniCommandPrefix(text)).toBe(detectOmniCommandPrefix(text));
    }
  });
});
