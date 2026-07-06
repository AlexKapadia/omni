"""Config-driven routing table: task type -> provider/model chain + budget.

Purpose: THE routing policy, expressed as one data structure — not code
sprawl. Each task type maps to a primary slot plus fallback slots; a slot
is either fixed or conditional on Anthropic being keyed (the optional
third provider is PROMOTED when a key exists, per the settled session
decision: Groq + Gemini are the required pair).
Pipeline position: consulted by ``engine.router.fallback_executor`` at
call time via :func:`resolve_route`; pure data + a pure resolution
function, so both keyed worlds are trivially testable.

Deny-by-default invariant: a task type absent from the table refuses to
route (``UnknownTaskTypeError``) — there is no wildcard row.
"""

from dataclasses import dataclass

from engine.router.completion_contract import Provider, TaskType
from engine.router.router_errors import MisconfiguredRouteError, UnknownTaskTypeError

# Model identifiers, named once so a model bump is a one-line change.
GROQ_FAST_MODEL = "llama-3.3-70b-versatile"
GEMINI_FLASH_MODEL = "gemini-2.5-flash"
GEMINI_PRO_MODEL = "gemini-2.5-pro"
ANTHROPIC_MODEL = "claude-sonnet-4-5"


@dataclass(frozen=True)
class ProviderModelSlot:
    """A concrete provider+model choice in a chain."""

    provider: Provider
    model: str


@dataclass(frozen=True)
class AnthropicIfKeyedSlot:
    """A conditional slot: Anthropic when keyed, ``otherwise`` when not."""

    otherwise: ProviderModelSlot
    anthropic_model: str = ANTHROPIC_MODEL


RouteSlot = ProviderModelSlot | AnthropicIfKeyedSlot

_GROQ_FAST = ProviderModelSlot(Provider.GROQ, GROQ_FAST_MODEL)
_GEMINI_FLASH = ProviderModelSlot(Provider.GEMINI, GEMINI_FLASH_MODEL)
_GEMINI_PRO = ProviderModelSlot(Provider.GEMINI, GEMINI_PRO_MODEL)


@dataclass(frozen=True)
class RouteSpec:
    """One routing-table row: ordered slots + the task's latency budget.

    ``latency_budget_p95_ms`` doubles as the per-attempt timeout the
    executor passes to clients; live paths must hold p95 < 1200 ms.
    """

    primary: RouteSlot
    fallbacks: tuple[RouteSlot, ...]
    latency_budget_p95_ms: int


# ---------------------------------------------------------------------------
# THE routing policy (session decision, settled):
#   live_extraction   groq -> gemini-flash                       (live, <1.2s)
#   intent_parsing    groq -> anthropic-if-keyed else gemini-flash (live, <1.2s)
#   enhanced_notes    anthropic-if-keyed else gemini-pro -> gemini-flash
#   ask_synthesis     anthropic-if-keyed else gemini-flash -> gemini-flash,
#                     gemini-pro as last resort (dedup removes repeats)
#   long_context_bulk gemini-flash -> anthropic-if-keyed else gemini-pro
#   agentic_tools     anthropic-if-keyed else gemini-flash (function calling)
#                     -> gemini-flash, gemini-pro
#   dictation_cleanup groq -> gemini-flash            (live dictation, <0.8s)
# ---------------------------------------------------------------------------
ROUTING_TABLE: dict[TaskType, RouteSpec] = {
    TaskType.LIVE_EXTRACTION: RouteSpec(
        primary=_GROQ_FAST,
        fallbacks=(_GEMINI_FLASH,),
        latency_budget_p95_ms=1200,  # live path: p95 < 1.2 s
    ),
    TaskType.INTENT_PARSING: RouteSpec(
        primary=_GROQ_FAST,
        fallbacks=(AnthropicIfKeyedSlot(otherwise=_GEMINI_FLASH),),
        latency_budget_p95_ms=1200,  # live path: p95 < 1.2 s
    ),
    TaskType.ENHANCED_NOTES: RouteSpec(
        primary=AnthropicIfKeyedSlot(otherwise=_GEMINI_PRO),
        fallbacks=(_GEMINI_FLASH,),
        latency_budget_p95_ms=20_000,  # post-meeting batch: quality over speed
    ),
    TaskType.ASK_SYNTHESIS: RouteSpec(
        primary=AnthropicIfKeyedSlot(otherwise=_GEMINI_FLASH),
        fallbacks=(_GEMINI_FLASH, _GEMINI_PRO),
        latency_budget_p95_ms=3_500,  # interactive Q&A
    ),
    TaskType.LONG_CONTEXT_BULK: RouteSpec(
        primary=_GEMINI_FLASH,
        fallbacks=(AnthropicIfKeyedSlot(otherwise=_GEMINI_PRO),),
        latency_budget_p95_ms=30_000,  # bulk long-context work
    ),
    TaskType.AGENTIC_TOOLS: RouteSpec(
        primary=AnthropicIfKeyedSlot(otherwise=_GEMINI_FLASH),
        fallbacks=(_GEMINI_FLASH, _GEMINI_PRO),
        latency_budget_p95_ms=8_000,  # tool-use turns
    ),
    TaskType.DICTATION_CLEANUP: RouteSpec(
        primary=_GROQ_FAST,
        fallbacks=(_GEMINI_FLASH,),
        # Tightest budget in the table: cleanup sits INSIDE the release->text
        # dictation path (<1.2 s end-to-end), so its slice is 800 ms — a slow
        # cleanup degrades to raw verbatim rather than delaying the user.
        latency_budget_p95_ms=800,
    ),
}


@dataclass(frozen=True)
class ResolvedRoute:
    """The concrete, keyed-world-specific attempt chain for one task."""

    task_type: TaskType
    attempts: tuple[ProviderModelSlot, ...]
    latency_budget_p95_ms: int


def _flatten_slot(slot: RouteSlot, keyed_providers: frozenset[str]) -> ProviderModelSlot:
    """Collapse a conditional slot for the current keyed world."""
    if isinstance(slot, AnthropicIfKeyedSlot):
        if Provider.ANTHROPIC.value in keyed_providers:
            return ProviderModelSlot(Provider.ANTHROPIC, slot.anthropic_model)
        return slot.otherwise
    return slot


def resolve_route(task_type: str, keyed_providers: frozenset[str]) -> ResolvedRoute:
    """Resolve a task type into its ordered provider/model attempt chain.

    - Unknown task types are REFUSED (deny by default).
    - Conditional slots collapse per ``keyed_providers``.
    - Un-keyed providers are dropped entirely: a call without a key can
      only auth-fail, so it never enters the chain (fail closed + no
      wasted latency).
    - Duplicate provider+model pairs dedupe, order-preserving.
    - An empty resulting chain raises ``MisconfiguredRouteError``.
    """
    try:
        known_task = TaskType(task_type)
    except ValueError:
        raise UnknownTaskTypeError(task_type) from None
    spec = ROUTING_TABLE[known_task]  # every TaskType has a row (tested)
    attempts: list[ProviderModelSlot] = []
    for slot in (spec.primary, *spec.fallbacks):
        concrete = _flatten_slot(slot, keyed_providers)
        if concrete.provider.value not in keyed_providers:
            continue  # fail closed: never attempt an un-keyed provider
        if concrete not in attempts:
            attempts.append(concrete)  # dedupe, order preserved
    if not attempts:
        raise MisconfiguredRouteError(task_type)
    return ResolvedRoute(
        task_type=known_task,
        attempts=tuple(attempts),
        latency_budget_p95_ms=spec.latency_budget_p95_ms,
    )
