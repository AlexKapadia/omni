"""Managed-region rewrites preserve every byte outside the markers — exactly.

The binding invariant under test: Omni never edits user-authored text.
Property-style: randomized user content (unicode, emoji, CJK, RTL, mixed
CRLF/LF/CR endings, marker look-alikes) surrounds the managed regions;
after any number of rewrites the bytes outside the marker lines must be
identical to the originals.
"""

import random

from engine.vault.managed_region_rewriter import (
    REGION_ACTIONS,
    REGION_ENHANCED_NOTES,
    close_marker,
    open_marker,
    rewrite_managed_region,
)

# Deliberately hostile pool: unicode scripts, emoji, markdown syntax,
# marker LOOK-ALIKES (wrong id / no spaces / truncated sentinel) that must
# NOT be treated as this region's markers.
_LINE_POOL = [
    "plain notes line",
    "谢谢，会议要点如下：",  # noqa: RUF001 — fullwidth punctuation is the hostile input
    "🚀🎯 emoji bullet",
    "مرحبا بالجميع في الاجتماع",
    "שלום לכולם",
    "> quoted | with pipes || and [brackets]",
    "```",
    "code fence content <!-- not a marker -->",
    "<!-- omni:manage -->",
    "  <!-- omni:managed:some-other-region -->",
    "<!--omni:managed:enhanced-notes-->",
    "tabs\tand   spaces  ",
    "",
    "---",
    "## My Notes",
]
_ENDINGS = ["\n", "\r\n"]

# Replacement-text pool: like the user pool but WITHOUT the marker sentinel
# decoys — replacement text carrying "omni:managed" is (correctly) refused
# by the injection guard, which has its own dedicated tests.
_REPLACEMENT_POOL = [line for line in _LINE_POOL if "omni:manage" not in line]


def _random_block(rng: random.Random, line_count: int, pool: list[str] | None = None) -> str:
    """Random user-authored text with mixed line endings."""
    lines = pool if pool is not None else _LINE_POOL
    return "".join(
        rng.choice(lines) + rng.choice(_ENDINGS) for _ in range(line_count)
    )


def _build_note(rng: random.Random) -> tuple[bytes, bytes, bytes, bytes]:
    """A synthetic note: (full, prefix, middle, suffix) — regions between them."""
    prefix = _random_block(rng, rng.randint(0, 12)).encode("utf-8")
    middle = _random_block(rng, rng.randint(1, 8)).encode("utf-8")
    suffix = _random_block(rng, rng.randint(0, 12)).encode("utf-8")
    ending = rng.choice(_ENDINGS).encode("utf-8")
    region_a = (
        open_marker(REGION_ENHANCED_NOTES).encode("utf-8") + ending
        + b"old enhanced" + ending
        + close_marker(REGION_ENHANCED_NOTES).encode("utf-8") + ending
    )
    region_b = (
        open_marker(REGION_ACTIONS).encode("utf-8") + ending
        + b"old actions" + ending
        + close_marker(REGION_ACTIONS).encode("utf-8") + ending
    )
    full = prefix + region_a + middle + region_b + suffix
    return full, prefix, middle, suffix


def _outside_spans(content: bytes, region_id: str) -> tuple[bytes, bytes]:
    """(bytes up to and incl. open-marker line, bytes from close-marker line on)."""
    lines = content.splitlines(keepends=True)
    open_bytes = open_marker(region_id).encode("utf-8")
    close_bytes = close_marker(region_id).encode("utf-8")
    open_index = next(i for i, ln in enumerate(lines) if ln.strip() == open_bytes)
    close_index = next(i for i, ln in enumerate(lines) if ln.strip() == close_bytes)
    return b"".join(lines[: open_index + 1]), b"".join(lines[close_index:])


def test_randomized_rewrites_never_touch_bytes_outside_markers() -> None:
    """Property: for many random notes and rewrites, outside bytes are exact."""
    for seed in range(40):
        rng = random.Random(seed)
        content, _, _, _ = _build_note(rng)
        for region_id in (REGION_ENHANCED_NOTES, REGION_ACTIONS):
            before_prefix, before_suffix = _outside_spans(content, region_id)
            new_inner = _random_block(rng, rng.randint(0, 6), _REPLACEMENT_POOL) or "replaced"
            rewritten = rewrite_managed_region(content, region_id, new_inner)
            after_prefix, after_suffix = _outside_spans(rewritten, region_id)
            assert after_prefix == before_prefix, f"seed={seed} region={region_id}"
            assert after_suffix == before_suffix, f"seed={seed} region={region_id}"
            content = rewritten  # rewrites compound; invariant must still hold


def _region_span(content: bytes, region_id: str) -> bytes:
    """The full region span: open-marker line through close-marker line."""
    lines = content.splitlines(keepends=True)
    open_bytes = open_marker(region_id).encode("utf-8")
    close_bytes = close_marker(region_id).encode("utf-8")
    open_index = next(i for i, ln in enumerate(lines) if ln.strip() == open_bytes)
    close_index = next(i for i, ln in enumerate(lines) if ln.strip() == close_bytes)
    return b"".join(lines[open_index : close_index + 1])


def test_rewriting_one_region_leaves_the_other_region_byte_identical() -> None:
    """Regions are independent: region A's rewrite must not disturb region B."""
    for seed in range(20):
        rng = random.Random(1000 + seed)
        content, _, _, _ = _build_note(rng)
        region_b_before = _region_span(content, REGION_ACTIONS)
        rewritten = rewrite_managed_region(content, REGION_ENHANCED_NOTES, "new A")
        # Region B's entire span (markers AND inner) lies outside region A
        # and must therefore be byte-identical after A's rewrite.
        assert _region_span(rewritten, REGION_ACTIONS) == region_b_before, f"seed={seed}"


def test_rewrite_is_idempotent_same_inner_twice_yields_identical_bytes() -> None:
    """Same write twice = byte-identical file (idempotency)."""
    rng = random.Random(7)
    content, _, _, _ = _build_note(rng)
    once = rewrite_managed_region(content, REGION_ENHANCED_NOTES, "stable content\nline 2")
    twice = rewrite_managed_region(once, REGION_ENHANCED_NOTES, "stable content\nline 2")
    assert once == twice


def test_crlf_user_file_endings_survive_and_inner_is_lf() -> None:
    """A CRLF-authored note keeps its CRLFs outside; new inner is LF-composed."""
    content = (
        "# Title\r\n"
        "user line one\r\n"
        f"{open_marker(REGION_ACTIONS)}\r\n"
        "old\r\n"
        f"{close_marker(REGION_ACTIONS)}\r\n"
        "user line two\r\n"
    ).encode()
    rewritten = rewrite_managed_region(content, REGION_ACTIONS, "new inner")
    assert rewritten.startswith(b"# Title\r\nuser line one\r\n")
    assert rewritten.endswith(f"{close_marker(REGION_ACTIONS)}\r\nuser line two\r\n".encode())
    assert b"new inner\n" in rewritten


def test_indented_markers_are_recognised_and_their_bytes_preserved() -> None:
    """A user-indented marker line still bounds the region and keeps its bytes."""
    content = (
        f"  {open_marker(REGION_ACTIONS)}\n"
        "old\n"
        f"\t{close_marker(REGION_ACTIONS)}"  # no trailing newline at EOF
    ).encode()
    rewritten = rewrite_managed_region(content, REGION_ACTIONS, "new")
    assert rewritten.startswith(f"  {open_marker(REGION_ACTIONS)}\n".encode())
    assert rewritten.endswith(f"\t{close_marker(REGION_ACTIONS)}".encode())


def test_empty_replacement_empties_the_region_and_region_stays_rewritable() -> None:
    """Emptying a region keeps both markers; a later rewrite still works."""
    content = (
        f"before\n{open_marker(REGION_ACTIONS)}\nold\n{close_marker(REGION_ACTIONS)}\nafter\n"
    ).encode()
    emptied = rewrite_managed_region(content, REGION_ACTIONS, "")
    assert (
        f"{open_marker(REGION_ACTIONS)}\n{close_marker(REGION_ACTIONS)}\n".encode() in emptied
    )
    refilled = rewrite_managed_region(emptied, REGION_ACTIONS, "again")
    assert b"again\n" in refilled
    assert refilled.startswith(b"before\n")
    assert refilled.endswith(b"after\n")
