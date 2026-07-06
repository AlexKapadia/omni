/**
 * Safe markdown renderer for engine-produced enhanced notes.
 *
 * XSS-safe BY CONSTRUCTION: the markdown is parsed into React elements and
 * text nodes only — there is no dangerouslySetInnerHTML anywhere, so raw
 * HTML in the source (script tags, event handlers, iframes) renders as
 * literal text. Links become anchors ONLY for http(s) URLs; every other
 * scheme (javascript:, data:, vbscript:) stays inert text. The supported
 * subset mirrors what the enhancement prompt asks for: headings, bullet /
 * checkbox lists, blockquotes, bold, italic, inline code, paragraphs.
 */
import type { ReactNode } from "react";

const HEADING_PATTERN = /^(#{1,6})\s+(.*)$/;
const BULLET_PATTERN = /^[-*+]\s+(.*)$/;
const CHECKBOX_PATTERN = /^\[([ xX])\]\s+(.*)$/;
const LINK_PATTERN = /\[([^\]]+)\]\(([^)\s]+)\)/;

/** Only plain web URLs may become anchors — deny every other scheme. */
function isSafeHref(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/** Inline pass: code spans, links, bold, italics — everything else is text. */
export function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let remaining = text;
  let key = 0;
  while (remaining.length > 0) {
    // Italic emphasis deliberately renders as plain text — it is not
    // load-bearing and single-asterisk parsing is ambiguous with bullets.
    const code = remaining.match(/`([^`]+)`/);
    const link = remaining.match(LINK_PATTERN);
    const bold = remaining.match(/\*\*([^*]+)\*\*/);
    const candidates = [
      code ? { index: code.index ?? 0, length: code[0].length, kind: "code", match: code } : null,
      link ? { index: link.index ?? 0, length: link[0].length, kind: "link", match: link } : null,
      bold ? { index: bold.index ?? 0, length: bold[0].length, kind: "bold", match: bold } : null,
    ].filter((c): c is NonNullable<typeof c> => c !== null);
    if (candidates.length === 0) {
      nodes.push(remaining);
      break;
    }
    candidates.sort((a, b) => a.index - b.index);
    const first = candidates[0]!;
    if (first.index > 0) nodes.push(remaining.slice(0, first.index));
    const token = `${keyPrefix}-${key++}`;
    if (first.kind === "code") {
      nodes.push(<code key={token}>{first.match[1]}</code>);
    } else if (first.kind === "bold") {
      nodes.push(<strong key={token}>{first.match[1]}</strong>);
    } else {
      const label = first.match[1] ?? "";
      const href = first.match[2] ?? "";
      if (isSafeHref(href)) {
        // rel guards the opener; target keeps the app shell in place.
        nodes.push(
          <a key={token} href={href} target="_blank" rel="noreferrer noopener">
            {label}
          </a>,
        );
      } else {
        // Hostile scheme: render the LABEL as inert text, drop the URL.
        nodes.push(label);
      }
    }
    remaining = remaining.slice(first.index + first.length);
  }
  return nodes;
}

interface ListBlock {
  readonly kind: "list";
  readonly items: readonly { readonly text: string; readonly checkbox: boolean }[];
}
interface TextBlock {
  readonly kind: "heading" | "paragraph" | "quote" | "rule";
  readonly level?: number;
  readonly text: string;
}
type Block = ListBlock | TextBlock;

function parseBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  let list: { text: string; checkbox: boolean }[] | null = null;
  const flushList = (): void => {
    if (list !== null && list.length > 0) blocks.push({ kind: "list", items: list });
    list = null;
  };
  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.length === 0) {
      flushList();
      continue;
    }
    const heading = line.match(HEADING_PATTERN);
    if (heading !== null) {
      flushList();
      blocks.push({ kind: "heading", level: heading[1]!.length, text: heading[2] ?? "" });
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
      flushList();
      blocks.push({ kind: "rule", text: "" });
      continue;
    }
    const bullet = line.match(BULLET_PATTERN);
    if (bullet !== null) {
      const body = bullet[1] ?? "";
      const checkbox = body.match(CHECKBOX_PATTERN);
      list = list ?? [];
      list.push(
        checkbox !== null
          ? { text: checkbox[2] ?? "", checkbox: true }
          : { text: body, checkbox: false },
      );
      continue;
    }
    if (line.startsWith(">")) {
      flushList();
      blocks.push({ kind: "quote", text: line.replace(/^>\s?/, "") });
      continue;
    }
    flushList();
    blocks.push({ kind: "paragraph", text: line });
  }
  flushList();
  return blocks;
}

export function SafeMarkdown({ markdown }: { readonly markdown: string }) {
  const blocks = parseBlocks(markdown);
  return (
    <div className="flex flex-col gap-[var(--space-3)]">
      {blocks.map((block, index) => {
        const key = `md-${index}`;
        if (block.kind === "list") {
          return (
            <ul key={key} className="m-0 flex list-none flex-col gap-[var(--space-1)] p-0">
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`} className="flex gap-[var(--space-2)]">
                  <span aria-hidden="true" className="text-[var(--grey-400)]">
                    {item.checkbox ? "☐" : "•"}
                  </span>
                  <span>{renderInline(item.text, `${key}-${itemIndex}`)}</span>
                </li>
              ))}
            </ul>
          );
        }
        if (block.kind === "heading") {
          // All heading levels render as one section style — the pane is a
          // reading surface, not a document; hierarchy comes from spacing.
          return (
            <h4
              key={key}
              className="m-0 mt-[var(--space-2)] font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
              style={{ fontSize: 14, letterSpacing: "0.01em" }}
            >
              {renderInline(block.text, key)}
            </h4>
          );
        }
        if (block.kind === "rule") {
          return <hr key={key} className="border-t border-[var(--grey-200)]" />;
        }
        if (block.kind === "quote") {
          return (
            <blockquote
              key={key}
              className="m-0 border-l-2 border-[var(--grey-300)] pl-[var(--space-3)] text-[var(--grey-600)]"
            >
              {renderInline(block.text, key)}
            </blockquote>
          );
        }
        return (
          <p key={key} className="m-0" style={{ lineHeight: "var(--text-body-lh)" }}>
            {renderInline(block.text, key)}
          </p>
        );
      })}
    </div>
  );
}
