/**
 * SafeMarkdown: XSS safety by construction + the supported subset.
 *
 * Hostile enhanced-notes content (the engine sanitises model output, but the
 * UI must not TRUST that) renders as inert text: no script elements, no
 * event handlers, no javascript:/data: anchors — while legitimate markdown
 * (headings, checklists, bold, code, https links) renders properly.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SafeMarkdown } from "./meetings-safe-markdown";

afterEach(cleanup);

describe("XSS safety", () => {
  it("renders a script tag as literal text, never as an element", () => {
    const { container } = render(
      <SafeMarkdown markdown={'<script>alert("pwned")</script>'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/alert\("pwned"\)/)).toBeTruthy();
  });

  it("renders img/onerror payloads as text — no img element, no handler", () => {
    const { container } = render(
      <SafeMarkdown markdown={'<img src=x onerror="alert(1)">'} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("onerror");
  });

  it("never creates an anchor for javascript:, data:, or vbscript: links", () => {
    const hostile = [
      "[click me](javascript:alert(1))",
      "[data](data:text/html;base64,PHNjcmlwdD4=)",
      "[vb](vbscript:msgbox)",
      "[case](JAVASCRIPT:alert(1))",
    ].join("\n\n");
    const { container } = render(<SafeMarkdown markdown={hostile} />);
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("click me"); // label kept as text
    expect(container.textContent).not.toContain("javascript:alert"); // URL dropped
  });

  it("allows https links, hardened with rel + target", () => {
    const { container } = render(
      <SafeMarkdown markdown={"See [the doc](https://example.test/spec)."} />,
    );
    const anchor = container.querySelector("a");
    expect(anchor).not.toBeNull();
    expect(anchor!.getAttribute("href")).toBe("https://example.test/spec");
    expect(anchor!.getAttribute("rel")).toContain("noopener");
    expect(anchor!.getAttribute("target")).toBe("_blank");
  });

  it("never emits raw HTML from mixed hostile content inside valid markdown", () => {
    const { container } = render(
      <SafeMarkdown
        markdown={'## Summary\n- item with <iframe src="evil"></iframe> inline'}
      />,
    );
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toContain("<iframe");
  });
});

describe("supported subset", () => {
  it("renders headings, bullets, checkboxes, bold, and inline code", () => {
    const markdown = [
      "## Next Steps",
      "- [ ] Finish the **security review** — Me",
      "- plain bullet with `code span`",
      "",
      "A closing paragraph.",
    ].join("\n");
    const { container } = render(<SafeMarkdown markdown={markdown} />);
    expect(screen.getByRole("heading", { name: "Next Steps" })).toBeTruthy();
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("strong")!.textContent).toBe("security review");
    expect(container.querySelector("code")!.textContent).toBe("code span");
    expect(screen.getByText("A closing paragraph.")).toBeTruthy();
  });

  it("renders blockquotes and horizontal rules", () => {
    const { container } = render(
      <SafeMarkdown markdown={"> a quoted line\n\n---\n\nafter the rule"} />,
    );
    expect(container.querySelector("blockquote")!.textContent).toBe("a quoted line");
    expect(container.querySelector("hr")).not.toBeNull();
  });

  it("windows newlines parse identically to unix newlines", () => {
    const unix = render(<SafeMarkdown markdown={"## H\n- a\n- b"} />).container.innerHTML;
    cleanup();
    const windows = render(<SafeMarkdown markdown={"## H\r\n- a\r\n- b"} />).container
      .innerHTML;
    expect(windows).toBe(unix);
  });
});
