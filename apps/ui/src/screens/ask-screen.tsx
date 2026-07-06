/**
 * Ask Omni — one question over everything you know: query input, answer with
 * inline citation markers, and exact-source chips (note_path + line range,
 * the M3 §Cite contract).
 *
 * Answers come through the AskAnswerProvider interface (MOCK provider today;
 * the M3 retrieval pipeline swaps in unchanged). States: empty (the page
 * display + privacy line), thinking (shimmer, never a spinner), answered,
 * and error with a retry.
 */
import { useState, type FormEvent } from "react";
import { CitationChip } from "../components/citation-chip";
import { OmniButton } from "../components/button";
import { SkeletonShimmer } from "../components/skeleton-shimmer";
import {
  askQuestion,
  askStore,
  toggleCitation,
  useAsk,
  type AskAnswerProvider,
} from "../lib/ask-store";
import { createMockAskAnswerProvider } from "../lib/mock-ask-answer-provider";

/** MOCK provider until the M3 retrieval pipeline lands (same interface). */
const defaultProvider: AskAnswerProvider = createMockAskAnswerProvider();

function QueryInput({
  provider,
  emphasized,
}: {
  readonly provider: AskAnswerProvider;
  readonly emphasized: boolean;
}) {
  const [draft, setDraft] = useState("");
  const thinking = useAsk((s) => s.status === "thinking");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (thinking) return; // one question in flight at a time
    void askQuestion(askStore, provider, draft);
  };

  return (
    <form onSubmit={submit} className="relative w-full">
      <input
        type="text"
        aria-label="Ask Omni"
        placeholder="Ask across your meetings and notes"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        className={
          "w-full bg-transparent text-[var(--ink)] outline-none placeholder:text-[var(--grey-300)] " +
          (emphasized
            ? "border border-[var(--ink)]"
            : "border border-[var(--grey-300)] focus:border-[var(--ink)]")
        }
        // Doc: query input radius 12, padding 16px 20px, 15px prose.
        style={{ borderRadius: "var(--radius-card)", padding: "16px 20px", fontSize: 15 }}
      />
      <span
        aria-hidden
        className="absolute font-[family-name:var(--font-mono)] text-[var(--grey-400)]"
        style={{ right: 20, top: "50%", transform: "translateY(-50%)", fontSize: 11 }}
      >
        ↵
      </span>
    </form>
  );
}

export function AskScreen({
  provider = defaultProvider,
}: {
  readonly provider?: AskAnswerProvider;
}) {
  const status = useAsk((s) => s.status);
  const question = useAsk((s) => s.question);
  const answer = useAsk((s) => s.answer);
  const errorMessage = useAsk((s) => s.errorMessage);
  const openMarker = useAsk((s) => s.openCitationMarker);

  if (status === "empty") {
    return (
      <div className="flex h-full items-center justify-center">
        <div
          className="flex w-full flex-col items-center gap-[var(--space-8)] text-center"
          style={{ maxWidth: 720, padding: "72px 0" }}
        >
          <h1
            className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
            style={{
              fontSize: "var(--text-page-size)",
              lineHeight: "var(--text-page-lh)",
              letterSpacing: "var(--text-page-ls)",
            }}
          >
            Ask across everything you know
          </h1>
          <QueryInput provider={provider} emphasized={false} />
          <p className="m-0 text-[var(--grey-400)]" style={{ fontSize: 13 }}>
            Answers come from your vault only. Nothing leaves this device.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div
        className="mx-auto flex w-full flex-col gap-[var(--space-10)]"
        style={{ maxWidth: 720, padding: "72px 0" }}
      >
        <QueryInput provider={provider} emphasized />

        {status === "thinking" && (
          <div className="flex flex-col gap-[var(--space-3)]">
            <p
              className="m-0 italic text-[var(--grey-400)]"
              style={{ fontSize: 13 }}
            >
              “{question}”
            </p>
            <SkeletonShimmer lines={3} />
          </div>
        )}

        {status === "error" && (
          <div className="flex flex-col items-start gap-[var(--space-3)]">
            <p className="m-0 text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
              Could not answer that.
            </p>
            <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
              {errorMessage}
            </p>
            <OmniButton
              variant="secondary"
              onClick={() => void askQuestion(askStore, provider, question)}
            >
              Try again
            </OmniButton>
          </div>
        )}

        {status === "answered" && answer !== null && (
          <article aria-label="Answer" className="flex flex-col gap-[var(--space-4)]">
            <h2
              className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
              style={{
                fontSize: "var(--text-section-size)",
                lineHeight: "var(--text-section-lh)",
                letterSpacing: "var(--text-section-ls)",
              }}
            >
              {answer.headline}
            </h2>
            <p className="m-0 text-[var(--ink)]" style={{ fontSize: 15, lineHeight: 1.8 }}>
              {answer.prose.map((span, i) => (
                <span key={i}>
                  {span.strong ? <strong>{span.text}</strong> : span.text}
                  {span.citationMarker !== undefined && (
                    <sup
                      className="font-[family-name:var(--font-mono)] text-[var(--grey-400)]"
                      style={{ fontSize: "var(--text-meta-size)" }}
                    >
                      {" "}
                      [{span.citationMarker}]
                    </sup>
                  )}
                </span>
              ))}
            </p>
            <div className="flex flex-col gap-[var(--space-2)] border-t border-[var(--grey-200)] pt-[var(--space-4)]">
              {answer.citations.map((citation) => (
                <CitationChip
                  key={citation.marker}
                  citation={citation}
                  open={openMarker === citation.marker}
                  onToggle={() => toggleCitation(askStore, citation.marker)}
                />
              ))}
            </div>
          </article>
        )}
      </div>
    </div>
  );
}
