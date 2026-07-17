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
OPENAI_MINI_MODEL = "gpt-4o-mini"
OLLAMA_DEFAULT_MODEL = "llama3.2"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"
AZURE_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
LMSTUDIO_DEFAULT_MODEL = "local-model"


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
_OPENAI_MINI = ProviderModelSlot(Provider.OPENAI, OPENAI_MINI_MODEL)
_OLLAMA_DEFAULT = ProviderModelSlot(Provider.OLLAMA, OLLAMA_DEFAULT_MODEL)
_OPENROUTER_DEFAULT = ProviderModelSlot(Provider.OPENROUTER, OPENROUTER_DEFAULT_MODEL)
_AZURE_DEFAULT = ProviderModelSlot(Provider.AZURE_OPENAI, AZURE_OPENAI_DEFAULT_MODEL)
_LMSTUDIO_DEFAULT = ProviderModelSlot(Provider.LM_STUDIO, LMSTUDIO_DEFAULT_MODEL)


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
        fallbacks=(
            _GEMINI_FLASH,
            _GEMINI_PRO,
            _OPENAI_MINI,
            _OPENROUTER_DEFAULT,
            _AZURE_DEFAULT,
            _OLLAMA_DEFAULT,
            _LMSTUDIO_DEFAULT,
        ),
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


# User-facing summary model ids (Settings) → concrete provider+model slots.
# Only injected when that provider is keyed; never invents an unkeyed call.
SUMMARY_MODEL_PREFERENCES: dict[str, ProviderModelSlot] = {
    "gemini-2.5-flash": _GEMINI_FLASH,
    "gemini-2.5-pro": _GEMINI_PRO,
    "claude-sonnet-4-5": ProviderModelSlot(Provider.ANTHROPIC, ANTHROPIC_MODEL),
    "gpt-4o": ProviderModelSlot(Provider.OPENAI, "gpt-4o"),
    "gpt-4o-mini": _OPENAI_MINI,
    "llama3.2": _OLLAMA_DEFAULT,
    "ollama/llama3.2": _OLLAMA_DEFAULT,
    "gemma3:1b": ProviderModelSlot(Provider.OLLAMA, "gemma3:1b"),
}

# User-facing summary_provider setting ids (Settings) → concrete Provider.
# "builtin-ai" is Meetily-style local-via-Ollama, not a second runtime.
SUMMARY_PROVIDER_TO_PROVIDER: dict[str, Provider] = {
    "ollama": Provider.OLLAMA,
    "builtin-ai": Provider.OLLAMA,
    "gemini": Provider.GEMINI,
    "anthropic": Provider.ANTHROPIC,
    "openai": Provider.OPENAI,
}

# The default model used when the preferred provider is set but no explicit
# preferred_model accompanies it.
SUMMARY_PROVIDER_DEFAULT_MODEL: dict[Provider, str] = {
    Provider.OLLAMA: OLLAMA_DEFAULT_MODEL,
    Provider.GEMINI: GEMINI_FLASH_MODEL,
    Provider.ANTHROPIC: ANTHROPIC_MODEL,
    Provider.OPENAI: "gpt-4o",
}


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


def prefer_summary_model(
    route: ResolvedRoute,
    preferred_model: str | None,
    keyed_providers: frozenset[str] | None = None,
    preferred_provider: str | None = None,
) -> ResolvedRoute:
    """Put the user's summary provider/model first when it is keyed.

    Used whenever Settings passes preferred_* (enhanced_notes, ask_synthesis,
    live_extraction, selection translate, …) so the summary provider is not a
    no-op. ``preferred_provider`` (the ``summary_provider`` setting) wins
    when it maps to a keyed provider — it prepends that provider's slot,
    using ``preferred_model`` when given or the provider's own default
    model otherwise. Falls through to the existing model-id preference
    logic when the provider is unmapped/unkeyed. Unknown or unkeyed
    preferences leave the chain unchanged (never invent an unkeyed call).
    """
    keyed = keyed_providers if keyed_providers is not None else frozenset(
        a.provider.value for a in route.attempts
    )
    if preferred_provider is not None and preferred_provider.strip():
        mapped = SUMMARY_PROVIDER_TO_PROVIDER.get(preferred_provider.strip().lower())
        if mapped is not None and mapped.value in keyed:
            model = (
                preferred_model.strip()
                if preferred_model is not None and preferred_model.strip()
                else SUMMARY_PROVIDER_DEFAULT_MODEL[mapped]
            )
            return _prepend_slot(route, ProviderModelSlot(mapped, model))
    if preferred_model is None or not preferred_model.strip():
        return route
    key = preferred_model.strip()
    slot = SUMMARY_MODEL_PREFERENCES.get(key)
    if slot is not None:
        if slot.provider.value not in keyed:
            return route
        preferred = slot
    else:
        matching = [a for a in route.attempts if a.model == key]
        if not matching:
            return route
        preferred = matching[0]
    return _prepend_slot(route, preferred)


def _prepend_slot(route: ResolvedRoute, preferred: ProviderModelSlot) -> ResolvedRoute:
    rest = [a for a in route.attempts if a != preferred]
    return ResolvedRoute(
        task_type=route.task_type,
        attempts=(preferred, *rest),
        latency_budget_p95_ms=route.latency_budget_p95_ms,
    )
