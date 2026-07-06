"""Parser tests: wikilinks (aliases, anchors, nesting, code), headings, frontmatter.

Documented semantics under test (from the module docstring): innermost
brackets win; code fences and inline code yield no links; frontmatter is
LENIENT — malformed lines are skipped and never fatal (untrusted input
must not block indexing).
"""

from engine.index.wikilink_and_frontmatter_parser import (
    parse_frontmatter_lenient,
    parse_headings,
    parse_note,
    parse_wikilinks,
)


def test_plain_aliased_and_anchored_wikilinks() -> None:
    text = "See [[Priya Sharma]] and [[Acme Corp|the client]] re [[Plan#Q3|plan]]."
    links = parse_wikilinks(text)
    assert [(link.target, link.alias) for link in links] == [
        ("Priya Sharma", None),
        ("Acme Corp", "the client"),
        ("Plan", "plan"),  # #heading anchor stripped from the target
    ]
    assert all(link.line == 1 for link in links)


def test_nested_brackets_resolve_to_the_innermost_link() -> None:
    links = parse_wikilinks("weird [[outer [[inner]] tail]]")
    assert [link.target for link in links] == ["inner"]


def test_pure_anchor_and_empty_links_target_no_note() -> None:
    assert parse_wikilinks("see [[#Heading Only]] and [[]] and [[   ]]") == []


def test_links_inside_fenced_code_blocks_are_not_extracted() -> None:
    text = "before [[real]]\n```\n[[fenced away]]\n```\nafter [[also real]]\n"
    assert [link.target for link in parse_wikilinks(text)] == ["real", "also real"]


def test_tilde_fences_and_unclosed_fences_suppress_links() -> None:
    tilde = "~~~\n[[hidden]]\n~~~\n[[shown]]"
    assert [link.target for link in parse_wikilinks(tilde)] == ["shown"]
    unclosed = "```\n[[swallowed by unclosed fence]]\n"
    assert parse_wikilinks(unclosed) == []


def test_links_inside_inline_code_spans_are_not_extracted() -> None:
    text = "use `[[not a link]]` but [[a link]] works"
    assert [link.target for link in parse_wikilinks(text)] == ["a link"]


def test_wikilink_line_numbers_are_one_based() -> None:
    text = "first\n[[second-line link]]\n\n[[fourth-line link]]"
    assert [link.line for link in parse_wikilinks(text)] == [2, 4]


def test_headings_with_levels_lines_and_trailing_hash_cleanup() -> None:
    text = "# Top\nbody\n## Sub ##\n```\n# not a heading\n```\n###### Deep"
    headings = parse_headings(text)
    assert [(h.level, h.text, h.line) for h in headings] == [
        (1, "Top", 1),
        (2, "Sub", 3),
        (6, "Deep", 7),
    ]


def test_seven_hashes_is_not_a_heading() -> None:
    assert parse_headings("####### seven") == []


def test_frontmatter_scalars_lists_and_inline_arrays() -> None:
    text = (
        "---\n"
        "title: My Note\n"
        'quoted: "hello: world"\n'
        "tags:\n"
        "  - alpha\n"
        "  - beta\n"
        "inline: [a, b, c]\n"
        "empty_list:\n"
        "---\n"
        "body\n"
    )
    fields, body_start_line = parse_frontmatter_lenient(text)
    assert fields == {
        "title": "My Note",
        "quoted": "hello: world",
        "tags": ["alpha", "beta"],
        "inline": ["a", "b", "c"],
        "empty_list": [],
    }
    assert body_start_line == 10
    assert text.split("\n")[body_start_line - 1] == "body"


def test_malformed_frontmatter_lines_are_skipped_never_fatal() -> None:
    text = (
        "---\n"
        "good: value\n"
        "{{% totally not yaml %}}\n"
        ": no key\n"
        "good: duplicate ignored\n"
        "also_good: kept\n"
        "---\n"
        "body"
    )
    fields, _ = parse_frontmatter_lenient(text)
    assert fields == {"good": "value", "also_good": "kept"}


def test_unclosed_frontmatter_fence_means_no_frontmatter() -> None:
    text = "---\ntitle: never closed\nbody line"
    fields, body_start_line = parse_frontmatter_lenient(text)
    assert fields == {}
    assert body_start_line == 1  # whole document treated as body


def test_no_frontmatter_returns_empty_and_line_one() -> None:
    assert parse_frontmatter_lenient("just body") == ({}, 1)
    assert parse_frontmatter_lenient("") == ({}, 1)


def test_parse_note_combines_all_three_with_whole_file_line_numbers() -> None:
    text = (
        "---\n"
        "title: Combined\n"
        "---\n"
        "# Heading\n"
        "See [[Target|alias]].\n"
    )
    parsed = parse_note(text)
    assert parsed.frontmatter == {"title": "Combined"}
    assert parsed.body_start_line == 4
    assert [(h.text, h.line) for h in parsed.headings] == [("Heading", 4)]
    assert [(link.target, link.line) for link in parsed.wikilinks] == [("Target", 5)]


def test_adversarial_content_is_inert_data() -> None:
    """Injection-shaped content parses as plain strings — nothing executes,
    nothing raises."""
    text = (
        "---\n"
        "title: '; DROP TABLE chunks; --\n"
        "evil: ${jndi:ldap://x}\n"
        "---\n"
        "[[Robert'); DROP TABLE notes;--]]\n"
    )
    parsed = parse_note(text)
    # Unmatched leading quote is NOT stripped (only matching pairs are).
    assert parsed.frontmatter["title"] == "'; DROP TABLE chunks; --"
    assert parsed.wikilinks[0].target == "Robert'); DROP TABLE notes;--"
