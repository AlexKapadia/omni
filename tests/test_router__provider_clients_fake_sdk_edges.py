"""Provider-client edges via injected FAKE SDKs — request build + parse + errors.

These tests exercise the three provider clients (Groq / Anthropic / Gemini) and
the client registry WITHOUT any real network or real SDK. Each SDK is a fake
module injected into ``sys.modules`` so the client's own lazy loader
(``_load_*_sdk`` -> ``importlib.import_module`` -> ``sdk.<Client>(...)``) runs for
real. Every test ASSERTS an exact, load-bearing fact:

- the request payload the client builds (channel separation, model, budgets,
  tool/schema shaping) reaches the SDK exactly as specified;
- the SDK constructor is handed the REVEALED key and ``max_retries=0`` (retry
  policy belongs to the fallback executor, never the SDK);
- the response is normalised with provider-reported usage passed through EXACTLY
  and tool calls parsed faithfully;
- an SDK exception is translated to a typed, class-correct ``ProviderCallError``.

A test here only passes if the code is correct: wrong token, wrong role channel,
a dropped tool call, or a mis-classified error all make it FAIL.
"""

import sys
import types
from typing import Any

import pytest

from engine.router.completion_contract import (
    ChatMessage,
    CompletionRequest,
    Provider,
    ProviderCompletion,
    TaskType,
    ToolCall,
    ToolSpec,
)
from engine.router.provider_client_anthropic import AnthropicCompletionClient
from engine.router.provider_client_gemini import GeminiCompletionClient
from engine.router.provider_client_groq import GroqCompletionClient
from engine.router.provider_client_registry import build_provider_clients
from engine.router.router_errors import ProviderCallError, ProviderErrorClass
from engine.security.secret_redaction import SecretApiKey

FAKE_KEY = SecretApiKey("sk-fake-provider-key-0123456789")

_TOOL = ToolSpec(
    name="create_event",
    description="Create a calendar event",
    parameters_json_schema={"type": "object", "properties": {"title": {"type": "string"}}},
)


class _FakeStatusError(Exception):
    """SDK-shaped error carrying an HTTP ``status_code`` (groq/anthropic style)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _request(
    *,
    tools: tuple[ToolSpec, ...] = (),
    json_schema: dict[str, object] | None = None,
    messages: tuple[ChatMessage, ...] = (ChatMessage(role="user", content="ok"),),
    model: str = "the-model",
    max_tokens: int = 7,
    timeout_seconds: float = 12.5,
) -> CompletionRequest:
    return CompletionRequest(
        task_type=TaskType.INTENT_PARSING,
        model=model,
        system_frame="SYSTEM FRAME",
        messages=messages,
        timeout_seconds=timeout_seconds,
        tools=tools,
        json_schema=json_schema,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------


def _install_fake_groq(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: Any = None,
    exc: Exception | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {"ctor": None, "create": None}

    class _Completions:
        async def create(self, **kwargs: Any) -> Any:
            rec["create"] = kwargs
            if exc is not None:
                raise exc
            return response

    class _AsyncGroq:
        def __init__(self, **kwargs: Any) -> None:
            rec["ctor"] = kwargs
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setitem(sys.modules, "groq", types.SimpleNamespace(AsyncGroq=_AsyncGroq))
    return rec


def _groq_response(
    content: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    tool_calls: tuple[tuple[str, str], ...] = (),
) -> Any:
    calls = [
        types.SimpleNamespace(function=types.SimpleNamespace(name=n, arguments=a))
        for n, a in tool_calls
    ]
    message = types.SimpleNamespace(content=content, tool_calls=calls or None)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=message)],
        usage=types.SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


async def test_groq_builds_payload_and_reveals_key_with_zero_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_groq(monkeypatch, response=_groq_response("hello", 13, 4))
    client = GroqCompletionClient(FAKE_KEY)

    result = client.complete(_request(messages=(ChatMessage(role="user", content="hi there"),)))
    completion = await result

    # SDK constructor: key revealed, retries disabled (executor owns retries).
    assert rec["ctor"] == {"api_key": FAKE_KEY.reveal(), "max_retries": 0}
    # Channel separation: system frame is turn 0, data rides its own turn.
    assert rec["create"]["messages"] == [
        {"role": "system", "content": "SYSTEM FRAME"},
        {"role": "user", "content": "hi there"},
    ]
    assert rec["create"]["model"] == "the-model"
    assert rec["create"]["max_tokens"] == 7
    assert rec["create"]["timeout"] == 12.5
    # No tools / no schema requested -> neither key is present.
    assert "tools" not in rec["create"]
    assert "response_format" not in rec["create"]
    # Usage passes through EXACTLY (ledger depends on it); provider fixed.
    assert completion == ProviderCompletion(
        text="hello",
        provider=Provider.GROQ,
        model="the-model",
        prompt_tokens=13,
        completion_tokens=4,
        tool_calls=(),
    )


async def test_groq_none_content_becomes_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_groq(monkeypatch, response=_groq_response(None, 1, 0))
    completion = await GroqCompletionClient(FAKE_KEY).complete(_request())
    assert completion.text == ""  # `message.content or ""` — never None on the contract


async def test_groq_tools_shape_openai_function_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_groq(monkeypatch, response=_groq_response("ok", 2, 2))
    await GroqCompletionClient(FAKE_KEY).complete(_request(tools=(_TOOL,)))
    assert rec["create"]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "create_event",
                "description": "Create a calendar event",
                "parameters": _TOOL.parameters_json_schema,
            },
        }
    ]


async def test_groq_json_schema_requests_json_object_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_groq(monkeypatch, response=_groq_response("{}", 2, 1))
    await GroqCompletionClient(FAKE_KEY).complete(_request(json_schema={"type": "object"}))
    assert rec["create"]["response_format"] == {"type": "json_object"}


async def test_groq_parses_tool_calls_faithfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_groq(
        monkeypatch,
        response=_groq_response("", 5, 6, tool_calls=(("create_event", '{"title":"Sync"}'),)),
    )
    completion = await GroqCompletionClient(FAKE_KEY).complete(_request())
    # Groq passes the model's raw JSON argument text through verbatim —
    # name and argument text must both survive untouched.
    assert completion.tool_calls == (
        ToolCall(name="create_event", arguments_json='{"title":"Sync"}'),
    )


async def test_groq_error_is_translated_to_typed_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_groq(monkeypatch, exc=_FakeStatusError("rate limited", 429))
    with pytest.raises(ProviderCallError) as excinfo:
        await GroqCompletionClient(FAKE_KEY).complete(_request())
    assert excinfo.value.error_class is ProviderErrorClass.RATELIMIT
    assert excinfo.value.provider == "groq"
    assert excinfo.value.status_code == 429


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


def _install_fake_anthropic(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: Any = None,
    exc: Exception | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {"ctor": None, "create": None}

    class _Messages:
        async def create(self, **kwargs: Any) -> Any:
            rec["create"] = kwargs
            if exc is not None:
                raise exc
            return response

    class _AsyncAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            rec["ctor"] = kwargs
            self.messages = _Messages()

    monkeypatch.setitem(
        sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)
    )
    return rec


def _anthropic_response(
    blocks: tuple[tuple[Any, ...], ...],
    input_tokens: int,
    output_tokens: int,
) -> Any:
    content = []
    for block in blocks:
        if block[0] == "text":
            content.append(types.SimpleNamespace(type="text", text=block[1]))
        else:  # ("tool_use", name, input_dict)
            content.append(
                types.SimpleNamespace(type="tool_use", name=block[1], input=block[2])
            )
    return types.SimpleNamespace(
        content=content,
        usage=types.SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


async def test_anthropic_payload_puts_frame_in_system_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_anthropic(
        monkeypatch, response=_anthropic_response((("text", "hi"),), 20, 5)
    )
    completion = await AnthropicCompletionClient(FAKE_KEY).complete(
        _request(messages=(ChatMessage(role="user", content="q"),))
    )
    assert rec["ctor"] == {"api_key": FAKE_KEY.reveal(), "max_retries": 0}
    # system_frame goes to the top-level `system` param, NOT into messages.
    assert rec["create"]["system"] == "SYSTEM FRAME"
    assert rec["create"]["messages"] == [{"role": "user", "content": "q"}]
    assert rec["create"]["max_tokens"] == 7
    assert rec["create"]["timeout"] == 12.5
    assert completion.provider is Provider.ANTHROPIC
    assert completion.prompt_tokens == 20  # input_tokens -> prompt_tokens
    assert completion.completion_tokens == 5  # output_tokens -> completion_tokens


async def test_anthropic_concatenates_text_blocks_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_anthropic(
        monkeypatch,
        response=_anthropic_response((("text", "foo"), ("text", "bar")), 1, 1),
    )
    completion = await AnthropicCompletionClient(FAKE_KEY).complete(_request())
    assert completion.text == "foobar"  # "".join in block order


async def test_anthropic_tool_use_block_serialises_input_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_anthropic(
        monkeypatch,
        response=_anthropic_response(
            (("text", "sure"), ("tool_use", "create_event", {"title": "Sync"})), 3, 9
        ),
    )
    completion = await AnthropicCompletionClient(FAKE_KEY).complete(_request())
    assert completion.text == "sure"  # tool_use block contributes no text
    assert len(completion.tool_calls) == 1
    assert completion.tool_calls[0].name == "create_event"
    assert completion.tool_calls[0].arguments_json == '{"title": "Sync"}'


async def test_anthropic_tools_use_input_schema_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_anthropic(
        monkeypatch, response=_anthropic_response((("text", "x"),), 1, 1)
    )
    await AnthropicCompletionClient(FAKE_KEY).complete(_request(tools=(_TOOL,)))
    assert rec["create"]["tools"] == [
        {
            "name": "create_event",
            "description": "Create a calendar event",
            "input_schema": _TOOL.parameters_json_schema,  # NOT "parameters" (Messages API)
        }
    ]


async def test_anthropic_error_translated_to_auth_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_anthropic(monkeypatch, exc=_FakeStatusError("forbidden", 403))
    with pytest.raises(ProviderCallError) as excinfo:
        await AnthropicCompletionClient(FAKE_KEY).complete(_request())
    assert excinfo.value.error_class is ProviderErrorClass.AUTH
    assert excinfo.value.retryable is False  # a bad key is never retried
    assert excinfo.value.provider == "anthropic"


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


def _install_fake_genai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: Any = None,
    exc: Exception | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {"ctor": None, "create": None}

    class _Models:
        async def generate_content(self, **kwargs: Any) -> Any:
            rec["create"] = kwargs
            if exc is not None:
                raise exc
            return response

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            rec["ctor"] = kwargs
            self.aio = types.SimpleNamespace(models=_Models())

    monkeypatch.setitem(
        sys.modules, "google.genai", types.SimpleNamespace(Client=_Client)
    )
    return rec


def _genai_response(
    text: str | None,
    prompt_token_count: int | None,
    candidates_token_count: int | None,
    function_calls: tuple[tuple[str, dict[str, Any]], ...] = (),
) -> Any:
    calls = [types.SimpleNamespace(name=n, args=a) for n, a in function_calls]
    return types.SimpleNamespace(
        text=text,
        function_calls=calls or None,
        usage_metadata=types.SimpleNamespace(
            prompt_token_count=prompt_token_count,
            candidates_token_count=candidates_token_count,
        ),
    )


async def test_gemini_config_and_contents_channel_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_genai(monkeypatch, response=_genai_response("hi", 11, 3))
    completion = await GeminiCompletionClient(FAKE_KEY).complete(
        _request(
            messages=(
                ChatMessage(role="user", content="u1"),
                ChatMessage(role="assistant", content="a1"),
            )
        )
    )
    assert rec["ctor"] == {"api_key": FAKE_KEY.reveal()}
    assert rec["create"]["model"] == "the-model"
    # system_frame -> system_instruction; budget -> max_output_tokens.
    assert rec["create"]["config"]["system_instruction"] == "SYSTEM FRAME"
    assert rec["create"]["config"]["max_output_tokens"] == 7
    # Role mapping: assistant -> "model", user -> "user"; content is DATA parts.
    assert rec["create"]["contents"] == [
        {"role": "user", "parts": [{"text": "u1"}]},
        {"role": "model", "parts": [{"text": "a1"}]},
    ]
    assert completion.prompt_tokens == 11
    assert completion.completion_tokens == 3
    assert completion.provider is Provider.GEMINI


async def test_gemini_tools_use_function_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _install_fake_genai(monkeypatch, response=_genai_response("x", 1, 1))
    await GeminiCompletionClient(FAKE_KEY).complete(_request(tools=(_TOOL,)))
    assert rec["create"]["config"]["tools"] == [
        {
            "function_declarations": [
                {
                    "name": "create_event",
                    "description": "Create a calendar event",
                    "parameters": _TOOL.parameters_json_schema,
                }
            ]
        }
    ]


async def test_gemini_json_schema_sets_native_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema: dict[str, object] = {"type": "object", "properties": {"n": {"type": "integer"}}}
    rec = _install_fake_genai(monkeypatch, response=_genai_response("{}", 1, 1))
    await GeminiCompletionClient(FAKE_KEY).complete(_request(json_schema=schema))
    assert rec["create"]["config"]["response_mime_type"] == "application/json"
    assert rec["create"]["config"]["response_schema"] == schema


async def test_gemini_parses_function_calls_and_none_usage_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_genai(
        monkeypatch,
        response=_genai_response(
            None, None, None, function_calls=(("create_event", {"title": "Sync"}),)
        ),
    )
    completion = await GeminiCompletionClient(FAKE_KEY).complete(_request())
    assert completion.text == ""  # `response.text or ""`
    # None usage counts coerce to 0 (never crash the ledger).
    assert completion.prompt_tokens == 0
    assert completion.completion_tokens == 0
    assert len(completion.tool_calls) == 1
    assert completion.tool_calls[0].name == "create_event"
    assert completion.tool_calls[0].arguments_json == '{"title": "Sync"}'


async def test_gemini_error_translated_to_typed_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _GenaiApiError(Exception):
        def __init__(self, message: str, code: int) -> None:
            super().__init__(message)
            self.code = code

    _install_fake_genai(monkeypatch, exc=_GenaiApiError("boom", 500))
    with pytest.raises(ProviderCallError) as excinfo:
        await GeminiCompletionClient(FAKE_KEY).complete(_request())
    assert excinfo.value.error_class is ProviderErrorClass.SERVER
    assert excinfo.value.status_code == 500
    assert excinfo.value.provider == "gemini"


# ---------------------------------------------------------------------------
# Registry: one client per KEYED provider; unkeyed providers are absent.
# ---------------------------------------------------------------------------


class _FakeKeyStore:
    """Minimal ProviderKeyStore stand-in: returns a key only for named providers."""

    def __init__(self, keyed: dict[str, SecretApiKey]) -> None:
        self._keyed = keyed

    def get_key(self, provider: str) -> SecretApiKey | None:
        return self._keyed.get(provider)


def test_registry_builds_all_three_when_all_keyed() -> None:
    store = _FakeKeyStore(
        {p: SecretApiKey(f"key-for-{p}-000000") for p in ("groq", "gemini", "anthropic")}
    )
    clients = build_provider_clients(store)  # type: ignore[arg-type]
    assert set(clients) == {Provider.GROQ, Provider.GEMINI, Provider.ANTHROPIC}
    assert isinstance(clients[Provider.GROQ], GroqCompletionClient)
    assert isinstance(clients[Provider.GEMINI], GeminiCompletionClient)
    assert isinstance(clients[Provider.ANTHROPIC], AnthropicCompletionClient)


def test_registry_omits_unkeyed_providers() -> None:
    # Only Groq keyed: Gemini + Anthropic must be STRUCTURALLY absent
    # (un-keyed provider is uncallable, not "callable then 401").
    store = _FakeKeyStore({"groq": SecretApiKey("key-for-groq-000000")})
    clients = build_provider_clients(store)  # type: ignore[arg-type]
    assert set(clients) == {Provider.GROQ}
    assert Provider.GEMINI not in clients
    assert Provider.ANTHROPIC not in clients


def test_registry_empty_when_nothing_keyed() -> None:
    clients = build_provider_clients(_FakeKeyStore({}))  # type: ignore[arg-type]
    assert clients == {}


def test_registry_anthropic_only_promoted_when_keyed() -> None:
    # Gemini + Anthropic keyed, Groq NOT: proves each branch is independent.
    store = _FakeKeyStore(
        {"gemini": SecretApiKey("key-gemini-000000"), "anthropic": SecretApiKey("key-anth-000000")}
    )
    clients = build_provider_clients(store)  # type: ignore[arg-type]
    assert set(clients) == {Provider.GEMINI, Provider.ANTHROPIC}
    assert Provider.GROQ not in clients
