"""Kill-switch tests: engaged means ZERO cloud egress; local AI still routes.

Security invariant under test (claude.md §5.6 project binding): one flag
halts cloud/egress providers. Local providers (Ollama, LM Studio) remain
callable so offline Ollama-first still works. These tests prove cloud
clients are never touched while engaged, that garbled flag values fail
CLOSED, and that the runtime setter (the UI's instant stop) beats the
environment.
"""

from collections.abc import Iterator

import pytest

from engine.router.completion_contract import (
    ChatMessage,
    CompletionRequest,
    Provider,
    ProviderCompletion,
    ProviderCompletionClient,
)
from engine.router.fallback_executor import ProviderRouter
from engine.router.router_errors import KillSwitchEngagedError, UnknownTaskTypeError
from engine.router.router_ledger_repository import RouterLedgerEntry
from engine.router.routing_table import OLLAMA_DEFAULT_MODEL
from engine.security.kill_switch import (
    KILL_SWITCH_ENV_VAR,
    kill_switch_engaged,
    set_kill_switch_runtime_override,
)


@pytest.fixture(autouse=True)
def _clean_kill_switch_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts disengaged: env unset, runtime override cleared."""
    monkeypatch.delenv(KILL_SWITCH_ENV_VAR, raising=False)
    set_kill_switch_runtime_override(None)
    yield
    set_kill_switch_runtime_override(None)


class CountingClient(ProviderCompletionClient):
    """Fails the suite loudly if a cloud provider is reached while engaged."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self.calls = 0

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        self.calls += 1
        raise AssertionError(
            f"kill switch engaged but cloud provider {self.provider.value} was invoked"
        )


class OkClient(ProviderCompletionClient):
    """Returns a successful completion; records call count."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self.calls = 0

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        self.calls += 1
        return ProviderCompletion(
            text="local ok",
            provider=self.provider,
            model=request.model,
            prompt_tokens=1,
            completion_tokens=1,
        )


def _router() -> tuple[ProviderRouter, CountingClient, CountingClient, list[RouterLedgerEntry]]:
    groq = CountingClient(Provider.GROQ)
    gemini = CountingClient(Provider.GEMINI)
    entries: list[RouterLedgerEntry] = []

    async def record(entry: RouterLedgerEntry) -> None:
        entries.append(entry)

    router = ProviderRouter({Provider.GROQ: groq, Provider.GEMINI: gemini}, record)
    return router, groq, gemini, entries


def _router_with_ollama() -> tuple[
    ProviderRouter, CountingClient, CountingClient, OkClient, list[RouterLedgerEntry]
]:
    groq = CountingClient(Provider.GROQ)
    gemini = CountingClient(Provider.GEMINI)
    ollama = OkClient(Provider.OLLAMA)
    entries: list[RouterLedgerEntry] = []

    async def record(entry: RouterLedgerEntry) -> None:
        entries.append(entry)

    router = ProviderRouter(
        {Provider.GROQ: groq, Provider.GEMINI: gemini, Provider.OLLAMA: ollama},
        record,
    )
    return router, groq, gemini, ollama, entries


MESSAGES = (ChatMessage(role="user", content="data"),)

ALL_TASK_TYPES = [
    "live_extraction",
    "intent_parsing",
    "enhanced_notes",
    "ask_synthesis",
    "long_context_bulk",
    "agentic_tools",
]


# ---------------------------------------------------------------------------
# The flag itself (pure semantics, fail closed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_recognised_on_values_engage(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, value)
    assert kill_switch_engaged() is True


@pytest.mark.parametrize("value", ["", "0", "false", "FALSE", "no", "off", " 0 "])
def test_recognised_off_values_disengage(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, value)
    assert kill_switch_engaged() is False


@pytest.mark.parametrize("value", ["2", "banana", "tru", "0ff", "disable", "null", "-1"])
def test_garbled_values_fail_closed_engaged(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """A garbled security flag must never silently permit egress."""
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, value)
    assert kill_switch_engaged() is True


def test_unset_env_means_disengaged() -> None:
    assert kill_switch_engaged() is False


def test_runtime_override_beats_the_environment_both_ways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI's runtime setter is the user's instant stop/start — it wins
    over whatever the process was started with."""
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, "0")
    set_kill_switch_runtime_override(True)
    assert kill_switch_engaged() is True
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, "1")
    set_kill_switch_runtime_override(False)
    assert kill_switch_engaged() is False
    set_kill_switch_runtime_override(None)  # None reverts to the env flag
    assert kill_switch_engaged() is True


# ---------------------------------------------------------------------------
# The router refuses cloud — zero cloud client calls; local may still route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_type", ALL_TASK_TYPES)
async def test_engaged_switch_refuses_cloud_only_routes(
    monkeypatch: pytest.MonkeyPatch, task_type: str
) -> None:
    """With only cloud providers keyed, every task refuses — zero egress."""
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, "1")
    router, groq, gemini, entries = _router()
    with pytest.raises(KillSwitchEngagedError):
        await router.route(task_type, "frame", MESSAGES)
    assert groq.calls == 0 and gemini.calls == 0  # zero cloud egress
    assert entries == []  # nothing to log: no external call happened


@pytest.mark.parametrize("task_type", ["", "unknown", "LIVE_EXTRACTION", "../../etc"])
async def test_unknown_task_still_denied_while_kill_engaged(
    monkeypatch: pytest.MonkeyPatch, task_type: str
) -> None:
    """Kill switch does not invent routes: unknown tasks still deny-by-default
    (and cloud clients are never touched)."""
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, "1")
    router, groq, gemini, _ = _router()
    with pytest.raises(UnknownTaskTypeError):
        await router.route(task_type, "frame", MESSAGES)
    assert groq.calls == 0 and gemini.calls == 0


async def test_runtime_engage_refuses_cloud_without_restart() -> None:
    set_kill_switch_runtime_override(True)
    router, groq, _, _ = _router()
    with pytest.raises(KillSwitchEngagedError):
        await router.route("live_extraction", "frame", MESSAGES)
    assert groq.calls == 0


async def test_disengaged_switch_lets_unknown_tasks_be_denied_normally() -> None:
    """With the switch OFF the deny-by-default path is reachable again —
    proving the refusal above really was the switch, not the deny list."""
    router, _, _, _ = _router()
    with pytest.raises(UnknownTaskTypeError):
        await router.route("unknown", "frame", MESSAGES)


async def test_kill_switch_message_is_plain_voice_and_reassuring() -> None:
    set_kill_switch_runtime_override(True)
    router, _, _, _ = _router()
    with pytest.raises(KillSwitchEngagedError) as excinfo:
        await router.route("ask_synthesis", "frame", MESSAGES)
    message = str(excinfo.value)
    assert "kill switch" in message.lower()
    # The UI surfaces this directly: it must say local features keep working.
    assert "locally" in message or "local" in message


async def test_engaged_switch_still_routes_to_ollama_when_in_chain() -> None:
    """Kill switch is egress-only: Ollama in the resolved chain still runs."""
    set_kill_switch_runtime_override(True)
    router, groq, gemini, ollama, _ = _router_with_ollama()
    # ask_synthesis includes Ollama in fallbacks when keyed.
    result = await router.route("ask_synthesis", "frame", MESSAGES)
    assert result.provider is Provider.OLLAMA
    assert result.model == OLLAMA_DEFAULT_MODEL
    assert ollama.calls == 1
    assert groq.calls == 0 and gemini.calls == 0  # cloud never touched


async def test_engaged_switch_routes_ollama_first_via_preferred_provider() -> None:
    """Ollama-first settings still work offline under the kill switch."""
    set_kill_switch_runtime_override(True)
    router, groq, gemini, ollama, _ = _router_with_ollama()
    result = await router.route(
        "live_extraction",
        "frame",
        MESSAGES,
        preferred_provider="ollama",
        preferred_model="llama3.2",
    )
    assert result.provider is Provider.OLLAMA
    assert ollama.calls == 1
    assert groq.calls == 0 and gemini.calls == 0


async def test_engaged_switch_refuses_when_no_local_provider_remains() -> None:
    """live_extraction without a local preference has only cloud slots → refuse."""
    set_kill_switch_runtime_override(True)
    router, groq, gemini, ollama, entries = _router_with_ollama()
    with pytest.raises(KillSwitchEngagedError):
        await router.route("live_extraction", "frame", MESSAGES)
    assert groq.calls == 0 and gemini.calls == 0 and ollama.calls == 0
    assert entries == []
