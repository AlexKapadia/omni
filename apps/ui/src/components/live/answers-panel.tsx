/**
 * Answers panel (live meeting, floating bottom-right): surfaces an answer
 * when a question is heard in the room. Hits are MOCK today
 * (mock-live-answer-hits.ts, derived from the REAL transcript store); the M3
 * live retrieval tier swaps in behind the same hit shape.
 *
 * Design (components doc §04): open = 340px card, grey-200 border, the float
 * shadow, "panel hit" motion 200ms y +8 -> 0 with the shadow blooming, no
 * bounce. Collapsed = pill with an 8px breathing ring. Reduced motion is
 * honoured via useReducedMotion.
 */
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useState } from "react";
import { BreathingRing } from "../breathing-ring";
import { SectionLabel } from "../section-label";
import { tokenDurationSeconds } from "../../lib/design-token-motion";
import { deriveMockLiveAnswerHit } from "../../lib/mock-live-answer-hits";
import { useTranscript } from "../../lib/transcript-store";

export function AnswersPanel() {
  const segments = useTranscript((s) => s.segments);
  const [collapsed, setCollapsed] = useState(false);
  const reducedMotion = useReducedMotion();
  const hit = deriveMockLiveAnswerHit(segments);

  if (hit === null) return null; // no question heard yet — nothing to float

  const panelSeconds = reducedMotion ? 0 : tokenDurationSeconds("--dur-panel");

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className="absolute flex cursor-pointer items-center gap-[var(--space-2)] border-none bg-[var(--canvas)] text-[var(--grey-600)]"
        style={{
          right: 20,
          bottom: 20,
          borderRadius: "var(--radius-pill)",
          padding: "8px 16px",
          fontSize: 13, // doc: collapsed pill text 13px
          boxShadow: "var(--shadow-float)",
        }}
      >
        <BreathingRing size={8} breathing />
        1 answer · expand
      </button>
    );
  }

  return (
    <AnimatePresence>
      <motion.section
        key={hit.id}
        aria-label="Live answer"
        // Panel-hit motion: y +8 -> 0 with opacity and shadow bloom, no bounce.
        initial={{ opacity: 0, y: 8, boxShadow: "0 0 0 rgba(0,0,0,0)" }}
        animate={{ opacity: 1, y: 0, boxShadow: "var(--shadow-float)" }}
        transition={{ type: "tween", ease: [0, 0, 0.2, 1], duration: panelSeconds }}
        className="absolute flex flex-col border border-[var(--grey-200)] bg-[var(--canvas)]"
        style={{
          right: 20,
          bottom: 20,
          width: 340,
          borderRadius: "var(--radius-card)",
          padding: 20,
          gap: 10,
        }}
      >
        <div className="flex items-baseline justify-between">
          <SectionLabel>Answer</SectionLabel>
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            className="cursor-pointer border-none bg-transparent text-[var(--grey-400)] hover:text-[var(--ink)]"
            style={{ fontSize: "var(--text-meta-size)" }}
          >
            Collapse
          </button>
        </div>
        <p
          className="m-0 italic text-[var(--grey-400)]"
          style={{ fontSize: 13, lineHeight: "var(--text-transcript-lh)" }}
        >
          “{hit.questionHeard}”
        </p>
        <p
          className="m-0 text-[var(--ink)]"
          style={{ fontSize: "var(--text-body-size)", lineHeight: "var(--text-body-lh)" }}
        >
          {hit.answerProse.map((span, i) =>
            span.strong ? <strong key={i}>{span.text}</strong> : <span key={i}>{span.text}</span>,
          )}
        </p>
        <div
          className="border-t border-[var(--grey-200)] pt-[var(--space-2)] font-[family-name:var(--font-mono)] text-[var(--grey-400)]"
          style={{ fontSize: 11 }}
        >
          ↳ {hit.sourcePath} · {hit.sourceContext}
        </div>
      </motion.section>
    </AnimatePresence>
  );
}
