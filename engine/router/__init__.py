"""Omni engine AI router package: tri-provider egress with typed fallback.

Purpose: the ONLY path by which anything in the engine talks to an external
AI provider. Routing policy is a data table (``routing_table``); execution
is the fallback executor (kill-switch gated, retry-once, ledger-logged);
providers are Groq + Gemini (required pair) with Anthropic as the optional
promoted third slot.
Pipeline position: called by the M2+ pipelines (extraction, enhancement,
synthesis, agents); depends on ``engine.security`` for key custody and the
kill switch, and on ``engine.storage``'s database for the ledger.

Security invariants upheld package-wide:
- Kill switch halts ALL egress, fail closed, before any resolution.
- Unknown task types are refused (deny by default).
- Every external call lands one append-only ledger row, exact to the unit.
- Key material never enters this package — only ready-made clients do.
"""

from engine.router.completion_contract import (
    ChatMessage,
    CompletionRequest,
    Provider,
    ProviderCompletion,
    ProviderCompletionClient,
    RoutedCompletion,
    TaskType,
    ToolCall,
    ToolSpec,
)
from engine.router.fallback_executor import ProviderRouter
from engine.router.model_pricing import estimate_cost_usd
from engine.router.provider_client_registry import build_provider_clients
from engine.router.router_errors import (
    KillSwitchEngagedError,
    MisconfiguredRouteError,
    ProviderCallError,
    ProviderErrorClass,
    ProviderFailure,
    ProviderSdkMissingError,
    RouterError,
    RouterUnavailableError,
    UnknownTaskTypeError,
)
from engine.router.router_ledger_repository import (
    ProviderLedgerSummary,
    RouterLedgerEntry,
    insert_router_ledger_entry,
    recent_router_ledger_entries,
    summarize_router_ledger_by_provider,
)
from engine.router.routing_table import ROUTING_TABLE, ResolvedRoute, resolve_route

__all__ = [
    "ROUTING_TABLE",
    "ChatMessage",
    "CompletionRequest",
    "KillSwitchEngagedError",
    "MisconfiguredRouteError",
    "Provider",
    "ProviderCallError",
    "ProviderCompletion",
    "ProviderCompletionClient",
    "ProviderErrorClass",
    "ProviderFailure",
    "ProviderLedgerSummary",
    "ProviderRouter",
    "ProviderSdkMissingError",
    "ResolvedRoute",
    "RoutedCompletion",
    "RouterError",
    "RouterLedgerEntry",
    "RouterUnavailableError",
    "TaskType",
    "ToolCall",
    "ToolSpec",
    "UnknownTaskTypeError",
    "build_provider_clients",
    "estimate_cost_usd",
    "insert_router_ledger_entry",
    "recent_router_ledger_entries",
    "resolve_route",
    "summarize_router_ledger_by_provider",
]
