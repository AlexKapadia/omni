"""Live provider-key validation verdict logic — every branch, fakes only.

``validate_provider_key`` makes ONE real minimal call per provider and reports
the outcome exactly as observed. These tests drive every verdict branch with
injected fakes (no network): the kill-switch refusal, the no-key-saved short
circuit, the LLM completion path (success verdict, error verdict, and the
"key present but no client built" edge), and the Cartesia REST path (200 valid,
401/403 rejected, other-status, and transport-error). Each test asserts the
EXACT ``KeyValidationResult`` fields — a wrong verdict, a leaked branch, or a
mislabelled latency all make it FAIL.

Boundary note: the ONLY genuinely un-fakeable line is the raw ``httpx``/SDK
socket call itself; both are injected here (fake httpx module / monkeypatched
``build_provider_clients``), so all verdict logic around them is covered.
"""

import sys
import types
from collections.abc import Iterator
from typing import Any

import pytest

import engine.wiring.provider_key_live_validation as pkv
from engine.router.completion_contract import (
    CompletionRequest,
    Provider,
    ProviderCompletion,
    TaskType,
)
from engine.router.router_errors import ProviderCallError, ProviderErrorClass
from engine.router.routing_table import GROQ_FAST_MODEL
from engine.security.kill_switch import set_kill_switch_runtime_override
from engine.security.secret_redaction import SecretApiKey
from engine.voice.cartesia_message_framing import CARTESIA_API_VERSION


@pytest.fixture(autouse=True)
def _disengage_kill_switch() -> Iterator[None]:
    """Force the switch OFF for every test; reset to env-default afterward.

    Egress is only permitted with the switch disengaged, so validation tests
    need a known-off baseline. The engaged-case test flips it on locally.
    """
    set_kill_switch_runtime_override(False)
    yield
    set_kill_switch_runtime_override(None)


class _FakeStore:
    """ProviderKeyStore stand-in: returns a stored key only for named providers."""

    def __init__(self, keyed: dict[str, SecretApiKey]) -> None:
        self._keyed = keyed

    def get_key(self, provider: str) -> SecretApiKey | None:
        return self._keyed.get(provider)


class _FakeClient:
    """Provider client stub capturing the request; returns or raises on complete."""

    def __init__(self, *, result: ProviderCompletion | None = None,
                 exc: Exception | None = None) -> None:
        self.request: CompletionRequest | None = None
        self._result = result
        self._exc = exc

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        self.request = request
        if self._exc is not None:
            raise self._exc
        assert self._result is not None
        return self._result


# ---------------------------------------------------------------------------
# Top-level guards
# ---------------------------------------------------------------------------


async def test_kill_switch_engaged_refuses_without_any_call() -> None:
    set_kill_switch_runtime_override(True)  # fail closed on egress
    store = _FakeStore({"groq": SecretApiKey("key-groq-000000")})
    result = await pkv.validate_provider_key("groq", store)  # type: ignore[arg-type]
    assert result.valid is False
    assert result.latency_ms is None
    assert "kill switch engaged" in result.message


async def test_no_key_saved_short_circuits_before_any_call() -> None:
    result = await pkv.validate_provider_key("groq", _FakeStore({}))  # type: ignore[arg-type]
    assert result == pkv.KeyValidationResult(
        provider="groq", valid=False, message="no key saved for this provider", latency_ms=None
    )


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


async def test_llm_success_reports_valid_with_latency_and_probe_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeClient(
        result=ProviderCompletion(
            text="ok", provider=Provider.GROQ, model=GROQ_FAST_MODEL,
            prompt_tokens=1, completion_tokens=1,
        )
    )
    monkeypatch.setattr(
        pkv, "build_provider_clients", lambda store: {Provider.GROQ: fake_client}
    )
    store = _FakeStore({"groq": SecretApiKey("key-groq-000000")})

    result = await pkv.validate_provider_key("groq", store)  # type: ignore[arg-type]

    assert result.valid is True
    assert result.provider == "groq"
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert "key is valid" in result.message
    # The probe is the cheapest possible: 1 token, INTENT_PARSING lane, the
    # provider's cheapest routed model, single trivial turn.
    probe = fake_client.request
    assert probe is not None
    assert probe.max_tokens == 1
    assert probe.task_type is TaskType.INTENT_PARSING
    assert probe.model == GROQ_FAST_MODEL
    assert probe.system_frame == "Reply with the single word: ok"


async def test_llm_error_reports_invalid_with_redacted_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    err = ProviderCallError(
        provider="groq", model=GROQ_FAST_MODEL, error_class=ProviderErrorClass.AUTH,
        message="401 unauthorized", status_code=401,
    )
    monkeypatch.setattr(
        pkv, "build_provider_clients", lambda store: {Provider.GROQ: _FakeClient(exc=err)}
    )
    store = _FakeStore({"groq": SecretApiKey("key-groq-000000")})

    result = await pkv.validate_provider_key("groq", store)  # type: ignore[arg-type]

    assert result.valid is False
    assert result.latency_ms is None  # no latency claimed on a failed probe
    assert result.message == str(err)  # the client's already-redacted story, verbatim


async def test_llm_key_present_but_no_client_built_reports_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Edge: store yields a key but the registry declined to build a client.
    monkeypatch.setattr(pkv, "build_provider_clients", lambda store: {})
    store = _FakeStore({"groq": SecretApiKey("key-groq-000000")})
    result = await pkv.validate_provider_key("groq", store)  # type: ignore[arg-type]
    assert result.valid is False
    assert result.message == "no key saved for this provider"


# ---------------------------------------------------------------------------
# Cartesia REST path
# ---------------------------------------------------------------------------


def _install_fake_httpx(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int | None = None,
    http_error_name: str | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {"timeout": None, "get": None}

    class HTTPError(Exception):
        pass

    error_cls: type[Exception] = (
        type(http_error_name, (HTTPError,), {}) if http_error_name else HTTPError
    )

    class AsyncClient:
        def __init__(self, *, timeout: float | None = None) -> None:
            rec["timeout"] = timeout

        async def __aenter__(self) -> "AsyncClient":
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

        async def get(self, url: str, *, headers: dict[str, str] | None = None) -> Any:
            rec["get"] = {"url": url, "headers": headers}
            if http_error_name is not None:
                raise error_cls("transport failed")
            return types.SimpleNamespace(status_code=status_code)

    monkeypatch.setitem(
        sys.modules, "httpx", types.SimpleNamespace(HTTPError=HTTPError, AsyncClient=AsyncClient)
    )
    return rec


async def test_cartesia_200_is_valid_and_sends_auth_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_httpx(monkeypatch, status_code=200)
    store = _FakeStore({"cartesia": SecretApiKey("key-cartesia-000000")})

    result = await pkv.validate_provider_key("cartesia", store)  # type: ignore[arg-type]

    assert result.valid is True
    assert result.provider == "cartesia"
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert "key is valid" in result.message
    # Key revealed ONLY into the auth header; version header pinned to contract.
    assert rec["get"]["url"] == pkv._CARTESIA_VOICES_URL
    assert rec["get"]["headers"]["X-API-Key"] == "key-cartesia-000000"
    assert rec["get"]["headers"]["Cartesia-Version"] == CARTESIA_API_VERSION


@pytest.mark.parametrize("status", [401, 403])
async def test_cartesia_unauthorized_status_is_rejected(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _install_fake_httpx(monkeypatch, status_code=status)
    store = _FakeStore({"cartesia": SecretApiKey("key-cartesia-000000")})
    result = await pkv.validate_provider_key("cartesia", store)  # type: ignore[arg-type]
    assert result.valid is False
    assert result.latency_ms is None
    assert result.message == "Cartesia rejected the key (unauthorized)"


async def test_cartesia_other_status_reports_the_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch, status_code=500)
    store = _FakeStore({"cartesia": SecretApiKey("key-cartesia-000000")})
    result = await pkv.validate_provider_key("cartesia", store)  # type: ignore[arg-type]
    assert result.valid is False
    assert result.latency_ms is None
    assert result.message == "Cartesia answered with status 500"


async def test_cartesia_transport_error_reports_class_not_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch, http_error_name="ConnectTimeout")
    store = _FakeStore({"cartesia": SecretApiKey("key-cartesia-000000")})
    result = await pkv.validate_provider_key("cartesia", store)  # type: ignore[arg-type]
    assert result.valid is False
    assert result.latency_ms is None
    # Only the exception CLASS name surfaces — never the transport body.
    assert result.message == "could not reach Cartesia (ConnectTimeout)"
