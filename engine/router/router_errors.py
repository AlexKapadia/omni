"""Error taxonomy for the AI router: typed failures that drive fallback.

Purpose: one vocabulary for everything that can go wrong on the egress
path, so the fallback executor makes decisions on TYPES, not on string
matching. The taxonomy is deliberately small:

- ``auth``      -> the key is wrong/revoked. Retrying burns nothing but
                   time and rate-limit budget: NO retry, cascade at once.
- ``ratelimit`` -> transient quota pressure: retry once, then cascade.
- ``timeout``   -> the provider missed the task's latency budget: retry
                   once, then cascade.
- ``server``    -> provider-side 5xx (and anything unclassifiable — treated
                   as server so it stays retry-once + cascade, never fatal).

Pipeline position: raised by the provider clients, consumed by
``engine.router.fallback_executor``, surfaced to the UI as plain-voice
messages carried on :class:`RouterUnavailableError`.

Security invariant: every message stored on these errors has already been
scrubbed by ``engine.security.secret_redaction`` at the client boundary —
nothing here may reintroduce raw SDK text.
"""

from dataclasses import dataclass
from enum import StrEnum


class ProviderErrorClass(StrEnum):
    """The four failure classes the fallback policy is written against."""

    AUTH = "auth"
    RATELIMIT = "ratelimit"
    TIMEOUT = "timeout"
    SERVER = "server"


# Classes where a single same-provider retry is worth the latency.
RETRYABLE_ERROR_CLASSES = frozenset(
    {ProviderErrorClass.RATELIMIT, ProviderErrorClass.TIMEOUT, ProviderErrorClass.SERVER}
)


def classify_provider_status(status_code: int | None, *, timed_out: bool = False) -> (
    ProviderErrorClass
):
    """Map an HTTP status (or a timeout signal) onto the taxonomy.

    Unknown/unmappable failures classify as SERVER — the safest default:
    one retry, then fallback, never an unhandled crash of the router.
    """
    if timed_out:
        return ProviderErrorClass.TIMEOUT
    if status_code in (401, 403):
        return ProviderErrorClass.AUTH
    if status_code == 429:
        return ProviderErrorClass.RATELIMIT
    return ProviderErrorClass.SERVER


class RouterError(Exception):
    """Base class for every typed router failure."""


@dataclass(frozen=True)
class ProviderCallError(RouterError):
    """One provider attempt failed; the class drives the fallback decision.

    ``message`` is redacted at construction time by the raising client.
    """

    provider: str
    model: str
    error_class: ProviderErrorClass
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        return f"{self.provider}/{self.model} {self.error_class}: {self.message}"

    @property
    def retryable(self) -> bool:
        """May the SAME provider be retried once? (auth: never)."""
        return self.error_class in RETRYABLE_ERROR_CLASSES


@dataclass(frozen=True)
class ProviderFailure:
    """Compact record of why one provider was abandoned (for the UI)."""

    provider: str
    model: str
    error_class: ProviderErrorClass
    message: str


class RouterUnavailableError(RouterError):
    """Every provider in the task's chain failed; degrade gracefully.

    Carries WHICH providers failed and WHY so the UI can explain in plain
    voice instead of showing a stack trace.
    """

    def __init__(self, task_type: str, failures: tuple[ProviderFailure, ...]) -> None:
        self.task_type = task_type
        self.failures = failures
        detail = "; ".join(
            f"{f.provider} ({f.error_class}: {f.message})" for f in failures
        )
        super().__init__(
            f"All AI providers failed for task {task_type!r}: {detail or 'no providers keyed'}. "
            "Local capture, transcription, and your notes are unaffected."
        )


class KillSwitchEngagedError(RouterError):
    """The global kill switch is on: ALL external calls are refused.

    Fail closed (claude.md §5.6): raised BEFORE any provider client or task
    resolution runs, so no task type can route around it.
    """

    def __init__(self) -> None:
        super().__init__(
            "The kill switch is engaged: all external AI calls are halted. "
            "Capture, transcription, and vault features keep working locally."
        )


class UnknownTaskTypeError(RouterError):
    """Deny by default: a task type not in the routing table is refused."""

    def __init__(self, task_type: str) -> None:
        self.task_type = task_type
        super().__init__(
            f"Unknown task type {task_type!r}: refusing to route (deny by default)."
        )


class MisconfiguredRouteError(RouterError):
    """A task resolved to an empty provider chain (e.g. nothing keyed)."""

    def __init__(self, task_type: str) -> None:
        self.task_type = task_type
        super().__init__(
            f"No keyed provider is available for task {task_type!r}. "
            "Add your Groq and Gemini API keys in Settings."
        )


class ProviderSdkMissingError(RouterError):
    """A provider SDK is not installed; fail closed with the package name."""

    def __init__(self, provider: str, package_name: str) -> None:
        self.provider = provider
        self.package_name = package_name
        super().__init__(
            f"The {provider!r} provider requires the {package_name!r} package, "
            f"which is not installed. Install it with: pip install {package_name}"
        )
