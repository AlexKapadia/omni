"""Typed contract between the router and every provider client.

Purpose: the narrow, provider-agnostic interface the whole engine codes
against — ``complete(request) -> ProviderCompletion``. Callers (extraction,
enhancement, synthesis pipelines) build a :class:`CompletionRequest`; the
fallback executor picks provider+model; clients translate to their SDK.
Pipeline position: imported by the routing table, the provider clients,
the fallback executor, and every M2+ pipeline that calls the router.

Prompt-injection defence posture (claude.md §5.6): ``system_frame`` is the
CALLER-authored task framing and is the only instruction channel;
``messages`` carry transcript/document content as DATA. Provider clients
keep the two channels separate all the way into the SDK call — untrusted
content is never concatenated into the instruction channel. (The full
injection framework — sanitisation, canaries — lands with the M2 pipelines.)
"""

from dataclasses import dataclass, field
from enum import StrEnum


class TaskType(StrEnum):
    """Every kind of work the router knows how to place (deny all others)."""

    LIVE_EXTRACTION = "live_extraction"
    INTENT_PARSING = "intent_parsing"
    ENHANCED_NOTES = "enhanced_notes"
    ASK_SYNTHESIS = "ask_synthesis"
    LONG_CONTEXT_BULK = "long_context_bulk"
    AGENTIC_TOOLS = "agentic_tools"
    DICTATION_CLEANUP = "dictation_cleanup"


class Provider(StrEnum):
    """Cloud LLM providers. Groq + Gemini required; others optional."""

    GROQ = "groq"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    AZURE_OPENAI = "azure_openai"
    LM_STUDIO = "lm_studio"


@dataclass(frozen=True)
class ChatMessage:
    """One conversation turn. ``content`` from transcripts/documents is DATA
    (untrusted input) — never instructions."""

    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ToolSpec:
    """Provider-agnostic function/tool declaration (JSON-schema parameters)."""

    name: str
    description: str
    parameters_json_schema: dict[str, object]


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation the model requested (arguments as raw JSON text)."""

    name: str
    arguments_json: str


@dataclass(frozen=True)
class CompletionRequest:
    """Everything a provider client needs for one call.

    ``timeout_seconds`` comes from the routing table's latency budget —
    clients MUST enforce it and surface breaches as timeout-class errors.
    """

    task_type: TaskType
    model: str
    system_frame: str  # caller-authored instructions (trusted channel)
    messages: tuple[ChatMessage, ...]  # data channel (untrusted content)
    timeout_seconds: float
    tools: tuple[ToolSpec, ...] = ()
    json_schema: dict[str, object] | None = None  # structured-output request
    max_tokens: int = 4096


@dataclass(frozen=True)
class ProviderCompletion:
    """A successful provider response, normalised across SDKs.

    Token counts are the PROVIDER-REPORTED usage numbers — the ledger's
    cost arithmetic depends on them being passed through exactly, never
    estimated or rounded.
    """

    text: str
    provider: Provider
    model: str
    prompt_tokens: int
    completion_tokens: int
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class RoutedCompletion:
    """What the router hands back to callers: the completion plus which
    provider/model actually served it and the measured wall-clock latency
    (surfaced live in the UI — speed is a showcase feature)."""

    completion: ProviderCompletion
    provider: Provider
    model: str
    latency_ms: int
    attempts: int = field(default=1)  # 1 = primary succeeded first try


class ProviderCompletionClient:
    """Interface every provider client implements (kept as a plain base
    class, not a Protocol, so isinstance checks work in the registry).

    Implementations must:
    - enforce ``request.timeout_seconds``;
    - map every SDK failure onto :class:`ProviderCallError` with the right
      :class:`ProviderErrorClass` (see ``router_errors``);
    - redact their own key material from every error message.
    """

    provider: Provider

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        """Execute one completion call. Subclasses must override."""
        raise NotImplementedError
