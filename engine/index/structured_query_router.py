"""Deterministic first-pass query router: structured lookup vs hybrid.

Purpose: the M3 recommendation's "route first" step — entity lookups,
temporal queries, and frontmatter field queries are answered by EXACT SQL
(precise, fast, exact citations); everything else falls through to the
hybrid retriever. DENY NOTHING: an unclassifiable query is never rejected,
it just routes to hybrid.
Pipeline position: first stage of every Ask-Omni / live query; its
decision is executed by ``structured_sql_lookup_executor`` (structured
routes) or ``hybrid_rrf_retriever`` (hybrid).

Pure and deterministic by construction: the classifier takes the known
entity names and frontmatter fields as plain mappings (loaded from the DB
by the executor module) plus an explicit ``today`` — identical inputs
always classify identically (tested as a classification table).

Documented precedence (each rule tested):
1. Blank query → hybrid.
2. Action-verb start ("email Priya about March") → hybrid: an imperative
   is a task for the agent layer, not a lookup — even when an entity or a
   month appears in it (adversarial case from the brief).
3. Whole-query ``field: value`` / ``field=value`` with a known
   frontmatter field → frontmatter route.
4. Known entity name/alias present (word-boundary, possessive tolerated)
   → entity route, carrying any extracted date range as a filter.
5. Temporal expression alone → temporal route. The month "May" is only
   temporal after "in"/"during"/"since" (it is a common modal verb).
6. Anything else → hybrid.

Untrusted input: the query is data; the classifier only ever regex-scans
it. Extracted values are returned as fields, never embedded in SQL here.
"""

import calendar
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

ROUTE_ENTITY = "entity"
ROUTE_TEMPORAL = "temporal"
ROUTE_FRONTMATTER = "frontmatter"
ROUTE_HYBRID = "hybrid"

# Imperatives that make a query an ACTION (agent-layer work), not a lookup.
_ACTION_VERBS = frozenset(
    {"email", "send", "draft", "schedule", "remind", "create", "write", "message", "call", "book"}
)
_MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if number}
# "may" is ambiguous (modal verb): temporal only with an explicit preposition.
_AMBIGUOUS_MONTHS = frozenset({"may"})
_MONTH_PREPOSITIONS = ("in", "during", "since", "for", "from")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_YEAR = re.compile(r"\b(in|during|from|since)\s+((?:19|20)\d{2})\b")
_FRONTMATTER_QUERY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*[:=]\s*(.+?)\s*$")
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class RouteDecision:
    """The router's verdict plus everything the SQL executor needs."""

    route: str  # ROUTE_ENTITY | ROUTE_TEMPORAL | ROUTE_FRONTMATTER | ROUTE_HYBRID
    entity_ids: tuple[int, ...] = ()
    date_range: tuple[str, str] | None = None  # ISO dates, inclusive
    frontmatter_field: str | None = None
    frontmatter_value: str | None = None


def extract_date_range(query: str, today: date) -> tuple[str, str] | None:
    """Deterministic date/range extraction; all relatives anchor on ``today``.

    Supported (first match wins, in this order — tested): explicit ISO
    date(s), relative phrases (yesterday/today/last week/this week/last
    month/this month/last year), "in <year>", month names ("in March" —
    the most recent occurrence not in the future).
    """
    lowered = query.lower()
    iso_dates = sorted(m.group(0) for m in _ISO_DATE.finditer(lowered))
    if iso_dates:
        return iso_dates[0], iso_dates[-1]
    relative = _relative_range(lowered, today)
    if relative:
        return relative
    year_match = _YEAR.search(lowered)
    if year_match:
        year = int(year_match.group(2))
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    return _month_range(lowered, today)


def _phrase_present(lowered: str, phrase: str) -> bool:
    """Word-boundary phrase test ("today" must not fire inside "todays")."""
    return re.search(r"\b" + re.escape(phrase) + r"\b", lowered) is not None


def _relative_range(lowered: str, today: date) -> tuple[str, str] | None:
    """Fixed relative phrases; ISO weeks run Monday-Sunday. "yesterday" is
    checked before "today" (the latter is its substring, boundaries aside)."""
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    if _phrase_present(lowered, "yesterday"):
        day = today - timedelta(days=1)
        return day.isoformat(), day.isoformat()
    if _phrase_present(lowered, "today"):
        return today.isoformat(), today.isoformat()
    if _phrase_present(lowered, "last week"):
        start = week_start - timedelta(days=7)
        return start.isoformat(), (start + timedelta(days=6)).isoformat()
    if _phrase_present(lowered, "this week"):
        return week_start.isoformat(), (week_start + timedelta(days=6)).isoformat()
    if _phrase_present(lowered, "last month"):
        end = month_start - timedelta(days=1)
        return end.replace(day=1).isoformat(), end.isoformat()
    if _phrase_present(lowered, "this month"):
        last_day = calendar.monthrange(today.year, today.month)[1]
        return month_start.isoformat(), today.replace(day=last_day).isoformat()
    if _phrase_present(lowered, "last year"):
        year = today.year - 1
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    return None


def _month_range(lowered: str, today: date) -> tuple[str, str] | None:
    """Month-name extraction; ambiguous months need a preposition."""
    for token_match in _WORD.finditer(lowered):
        token = token_match.group(0)
        month = _MONTHS.get(token)
        if month is None:
            continue
        if token in _AMBIGUOUS_MONTHS:
            prefix = lowered[: token_match.start()].rstrip()
            if not prefix.endswith(_MONTH_PREPOSITIONS):
                continue  # "may" without a preposition is a verb, not a month
        # Most recent occurrence not in the future (documented semantics).
        year = today.year if month <= today.month else today.year - 1
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"
    return None


def match_entities(query: str, known_entities: Mapping[str, int]) -> tuple[int, ...]:
    """Entity ids whose name/alias appears on a word boundary (possessive ok).

    ``known_entities`` maps LOWERCASED canonical names and aliases to
    entity ids. Deterministic order: ascending id, deduplicated.
    """
    lowered = query.lower()
    found: set[int] = set()
    for name, entity_id in known_entities.items():
        if not name:
            continue
        pattern = r"\b" + re.escape(name) + r"(?:'s)?\b"
        if re.search(pattern, lowered):
            found.add(entity_id)
    return tuple(sorted(found))


def _starts_with_action_verb(lowered: str) -> bool:
    """True when the first meaningful token is an imperative action verb."""
    tokens = _WORD.findall(lowered)
    if tokens and tokens[0] == "please":
        tokens = tokens[1:]
    return bool(tokens) and tokens[0] in _ACTION_VERBS


def classify_query(
    query: str,
    known_entities: Mapping[str, int],
    known_frontmatter_fields: frozenset[str],
    today: date,
) -> RouteDecision:
    """Classify one query per the documented precedence. Never raises on
    arbitrary input — unknown shapes fall through to hybrid (deny nothing)."""
    lowered = query.lower().strip()
    if not lowered:
        return RouteDecision(route=ROUTE_HYBRID)
    if _starts_with_action_verb(lowered):
        return RouteDecision(route=ROUTE_HYBRID)
    frontmatter_match = _FRONTMATTER_QUERY.match(query)
    if frontmatter_match and frontmatter_match.group(1).lower() in known_frontmatter_fields:
        return RouteDecision(
            route=ROUTE_FRONTMATTER,
            frontmatter_field=frontmatter_match.group(1).lower(),
            frontmatter_value=frontmatter_match.group(2),
        )
    date_range = extract_date_range(lowered, today)
    entity_ids = match_entities(lowered, known_entities)
    if entity_ids:
        return RouteDecision(route=ROUTE_ENTITY, entity_ids=entity_ids, date_range=date_range)
    if date_range:
        return RouteDecision(route=ROUTE_TEMPORAL, date_range=date_range)
    return RouteDecision(route=ROUTE_HYBRID)
