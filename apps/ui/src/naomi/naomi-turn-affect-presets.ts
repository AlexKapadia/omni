/**
 * Turn-state → pool affect presets: the small pure map that lets the water
 * express where the conversation is (brief §2 emotion anchors). Idle rests,
 * listening leans in, thinking spirals inward, speaking animates — and when a
 * reply carries its own affect triple that wins during speaking.
 *
 * Extracted from NaomiView so the mapping is one named, testable concern and
 * the view stays focused on lifecycles/wiring. Pure and deterministic.
 */

import { clampAffect, type Affect, IDLE_AFFECT } from "./naomi-affect-types";
import type { NaomiTurnState } from "./naomi-turn-protocol";

export function affectForTurn(turnState: NaomiTurnState, replyAffect: Affect | null): Affect {
  switch (turnState) {
    case "listening":
      return clampAffect(0, 0.35, null); // "listening" anchor (a=0.35)
    case "thinking":
      return clampAffect(0.1, 0.45, null); // "thinking" anchor
    case "speaking":
      return replyAffect ?? clampAffect(0.1, 0.5, null); // reply affect wins if present
    case "idle":
    default:
      return IDLE_AFFECT;
  }
}
