"""Hand-rolled YAML frontmatter emit/parse for the narrow Omni schema.

Purpose: emit and parse the ONLY frontmatter shapes Omni writes — string
scalars, booleans, and flat lists of strings — with exact round-tripping.
Hand-rolled deliberately: no PyYAML dependency (supply-chain surface) and
no permissive YAML features (anchors, tags, multi-doc) that could be abused
by untrusted note content.
Pipeline position: used by the meeting/people/inbox writers for creation,
and by tests to prove round-trip exactness.

Security invariants:
- Fail closed: values outside the narrow schema (control characters,
  newlines) are refused at emit; frontmatter that doesn't parse under the
  narrow grammar raises ``FrontmatterFormatError`` rather than guessing.
- Untrusted values (titles, attendee names) are quoted/escaped so they can
  never break out of their value position and forge extra keys.
"""

import re
from collections.abc import Mapping, Sequence

from engine.vault.vault_errors import FrontmatterFormatError

FrontmatterValue = str | bool | list[str]

_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
# Plain (unquoted) scalars: conservative charset that no YAML parser can
# misread as a different type or structure.
_PLAIN_SCALAR_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._@/+()'-]*\Z")
_AMBIGUOUS_PLAIN = frozenset({"true", "false", "yes", "no", "on", "off", "null", "~"})
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def emit_frontmatter(fields: Mapping[str, FrontmatterValue | Sequence[str] | None]) -> str:
    """Emit a ``---``-fenced frontmatter block; ``None`` values are omitted.

    Key order follows the mapping's order. Raises ``FrontmatterFormatError``
    on keys/values outside the narrow schema (fail closed).
    """
    lines: list[str] = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if not _KEY_PATTERN.match(key):
            raise FrontmatterFormatError(f"illegal frontmatter key: {key!r}")
        lines.extend(_emit_field(key, value))
    lines.append("---")
    return "\n".join(lines) + "\n"


def _emit_field(key: str, value: FrontmatterValue | Sequence[str]) -> list[str]:
    """Emit the line(s) for one field."""
    if isinstance(value, bool):
        return [f"{key}: {'true' if value else 'false'}"]
    if isinstance(value, str):
        return [f"{key}: {emit_scalar(value)}"]
    if not isinstance(value, str) and isinstance(value, Sequence):
        items = list(value)
        if not all(isinstance(item, str) for item in items):
            raise FrontmatterFormatError(f"list field {key!r} must contain only strings")
        if not items:
            return [f"{key}: []"]
        return [f"{key}:", *(f"  - {emit_scalar(item)}" for item in items)]
    raise FrontmatterFormatError(f"unsupported frontmatter value type for {key!r}")


def emit_scalar(value: str) -> str:
    """Render one string scalar, quoting whenever the plain form is unsafe."""
    if _CONTROL_CHARS.search(value):
        # fail-closed: newlines/control chars can't round-trip in this schema.
        raise FrontmatterFormatError("control characters are not allowed in frontmatter values")
    needs_quotes = (
        not value
        or value != value.strip()
        or value.lower() in _AMBIGUOUS_PLAIN
        or not _PLAIN_SCALAR_PATTERN.match(value)
        or _looks_numeric(value)
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _looks_numeric(value: str) -> bool:
    """True if a YAML parser could read the plain form as a number."""
    try:
        float(value)
    except ValueError:
        return False
    return True


def parse_frontmatter(text: str) -> tuple[dict[str, FrontmatterValue], str]:
    """Parse a leading frontmatter block; return ``(fields, body)``.

    Only the narrow grammar this module emits is accepted; anything else
    raises ``FrontmatterFormatError`` (fail closed — never guess at user
    YAML). A file with no leading ``---`` returns ``({}, text)``.
    """
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        return {}, text
    fields: dict[str, FrontmatterValue] = {}
    index = 1
    while index < len(lines):
        line = lines[index].rstrip("\r")
        if line == "---":
            body = "\n".join(lines[index + 1 :])
            return fields, body
        index = _parse_field_lines(lines, index, fields)
    raise FrontmatterFormatError("frontmatter block never closed with '---'")


def _parse_field_lines(lines: list[str], index: int, fields: dict[str, FrontmatterValue]) -> int:
    """Parse one field starting at ``index``; return the next unparsed index."""
    line = lines[index].rstrip("\r")
    if not line.strip():
        return index + 1  # blank lines inside frontmatter are tolerated
    key, separator, rest = line.partition(":")
    if not separator or not _KEY_PATTERN.match(key):
        raise FrontmatterFormatError(f"unparseable frontmatter line: {line!r}")
    if key in fields:
        raise FrontmatterFormatError(f"duplicate frontmatter key: {key!r}")
    rest = rest.strip()
    if rest == "":
        items: list[str] = []
        index += 1
        while index < len(lines) and lines[index].rstrip("\r").startswith("  - "):
            items.append(parse_scalar(lines[index].rstrip("\r")[4:].strip()))
            index += 1
        fields[key] = items
        return index
    if rest == "[]":
        fields[key] = []
    elif rest in ("true", "false"):
        fields[key] = rest == "true"
    else:
        fields[key] = parse_scalar(rest)
    return index + 1


def parse_scalar(raw: str) -> str:
    """Parse one scalar value (quoted or plain) back to its string."""
    if raw.startswith('"'):
        if len(raw) < 2 or not raw.endswith('"'):
            raise FrontmatterFormatError(f"unterminated quoted scalar: {raw!r}")
        inner = raw[1:-1]
        result: list[str] = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch == "\\":
                if i + 1 >= len(inner) or inner[i + 1] not in ('"', "\\"):
                    raise FrontmatterFormatError(f"bad escape in scalar: {raw!r}")
                result.append(inner[i + 1])
                i += 2
            elif ch == '"':
                raise FrontmatterFormatError(f"unescaped quote inside scalar: {raw!r}")
            else:
                result.append(ch)
                i += 1
        return "".join(result)
    return raw
