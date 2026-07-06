"""Managed-region rewriting — the vault's information-boundary enforcer.

Purpose: the ONLY way Omni changes an existing note's content. A managed
region is the text strictly between an open marker line
``<!-- omni:managed:<region-id> -->`` and its close marker line
``<!-- /omni:managed:<region-id> -->``. Rewriting replaces the inside and
must leave every byte outside the two marker lines identical.
Pipeline position: called by the meeting-note writer's update operations
(enhanced notes / actions / transcript refresh).

Security invariants (binding — enforced here, not by convention):
- Byte-exact preservation: reassembly is done on the ORIGINAL byte lines;
  only the inner span is substituted. User CRLFs, BOMs, trailing
  no-newline lines, and encoding quirks outside the region all survive.
- Fail closed on ambiguity: zero/duplicated/unclosed/out-of-order markers,
  or any foreign marker nested inside the target region, refuse the
  rewrite (``ManagedRegionCorruptionError``) so a corrupted file is never
  "repaired" at the cost of user text.
- Marker recognition is line-wise and fence-blind BY DESIGN: a line that
  spells a marker inside a code fence still counts, which at worst makes
  the file ambiguous and REFUSES the write — never a wrong-span rewrite.
- Replacement text may not itself contain marker lines (region injection
  via model output is refused).
"""

import re

from engine.vault.vault_errors import ManagedRegionCorruptionError

# Region ids used by the meeting note. Ids are lowercase-kebab by contract.
REGION_ENHANCED_NOTES = "enhanced-notes"
REGION_ACTIONS = "actions"
REGION_TRANSCRIPT = "transcript"

_REGION_ID_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
# Any line carrying the managed-marker sentinel, well-formed or not — used
# for nesting/injection detection (fail closed on anything marker-like).
_MARKER_SENTINEL = b"omni:managed"


def open_marker(region_id: str) -> str:
    """The exact open-marker line text for a region."""
    return f"<!-- omni:managed:{region_id} -->"


def close_marker(region_id: str) -> str:
    """The exact close-marker line text for a region."""
    return f"<!-- /omni:managed:{region_id} -->"


def render_managed_region(region_id: str, inner_markdown: str) -> str:
    """Render a full managed block (markers + inner) for note CREATION."""
    _validate_region_id(region_id)
    _reject_marker_lines_in_replacement(inner_markdown)
    return f"{open_marker(region_id)}\n{inner_markdown.rstrip()}\n{close_marker(region_id)}"


def rewrite_managed_region(content: bytes, region_id: str, new_inner_markdown: str) -> bytes:
    """Replace the inside of one managed region; all other bytes unchanged.

    Inputs: the note's raw bytes, the target region id, and the replacement
    markdown (LF-composed; a trailing newline is ensured).
    Returns the new note bytes. Raises ``ManagedRegionCorruptionError`` on
    any marker ambiguity (fail closed — see module docstring).
    """
    _validate_region_id(region_id)
    _reject_marker_lines_in_replacement(new_inner_markdown)

    lines = content.splitlines(keepends=True)
    open_bytes = open_marker(region_id).encode("utf-8")
    close_bytes = close_marker(region_id).encode("utf-8")

    open_indices = [i for i, line in enumerate(lines) if line.strip() == open_bytes]
    close_indices = [i for i, line in enumerate(lines) if line.strip() == close_bytes]

    if len(open_indices) != 1 or len(close_indices) != 1:
        # fail-closed: zero or duplicated markers make the span ambiguous.
        raise ManagedRegionCorruptionError(
            f"region '{region_id}': expected exactly one open and one close marker, "
            f"found {len(open_indices)} open / {len(close_indices)} close — write refused"
        )
    open_index, close_index = open_indices[0], close_indices[0]
    if close_index <= open_index:
        # fail-closed: close before open is corruption, not a region.
        raise ManagedRegionCorruptionError(
            f"region '{region_id}': close marker precedes open marker — write refused"
        )
    for inner_line in lines[open_index + 1 : close_index]:
        if _MARKER_SENTINEL in inner_line:
            # fail-closed: another region's (or a malformed) marker nested
            # inside the target span would be destroyed by the rewrite.
            raise ManagedRegionCorruptionError(
                f"region '{region_id}': marker-like line nested inside the region — "
                "write refused"
            )

    inner = new_inner_markdown.rstrip("\n")
    new_inner_bytes = (inner + "\n").encode("utf-8") if inner else b""
    # Byte-exact reassembly: original lines (with their original endings)
    # before and after the span; only the inner bytes are new.
    prefix = b"".join(lines[: open_index + 1])
    suffix = b"".join(lines[close_index:])
    return prefix + new_inner_bytes + suffix


def _validate_region_id(region_id: str) -> None:
    """Region ids are lowercase-kebab only, so marker text is unambiguous."""
    if not _REGION_ID_PATTERN.match(region_id):
        raise ManagedRegionCorruptionError(f"invalid managed-region id: {region_id!r}")


def _reject_marker_lines_in_replacement(new_inner_markdown: str) -> None:
    """Refuse replacement text that smuggles marker lines (region injection)."""
    if _MARKER_SENTINEL.decode("ascii") in new_inner_markdown:
        # fail-closed: model/tool output must not manufacture or terminate
        # regions — that would let untrusted content edit outside its span.
        raise ManagedRegionCorruptionError(
            "replacement text contains a managed-marker sentinel — write refused"
        )
