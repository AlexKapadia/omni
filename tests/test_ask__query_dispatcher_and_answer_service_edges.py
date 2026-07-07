"""Ask edges: synthesis-output parsing fallbacks + the real gateway pipeline.

Two uncovered surfaces:
1. ``parse_synthesis_output`` — the tolerant JSON degradation ladder: a
   non-JSON reply, a JSON object missing/empty fields, and the first-line
   headline heuristic at its 80-char boundary. Every branch asserts the
   EXACT (headline, answer) pair, so a wrong degradation would fail.
2. ``AskAnswerGateway.answer`` — the real per-query lifecycle (migrate ->
   open connection -> BM25-only retriever -> router-bound ledger -> answer
   -> close) driven against a real empty SQLite DB. With nothing retrieved
   the honesty gate must return the canonical "not in your notes" answer
   with ZERO provider calls, so the injected router asserts it is never hit.
   Plus the default router factory builds a real (keyless) ProviderRouter.
"""

from pathlib import Path
from typing import Any, cast

import pytest

from engine.ask.ask_omni_answer_service import (
    FALLBACK_HEADLINE,
    parse_synthesis_output,
)
from engine.ask.ask_prompt_frames import NO_ANSWER_TEXT
from engine.ask.ask_query_command_dispatcher import (
    AskAnswerGateway,
    _default_ask_router_factory,
)
from engine.router import ProviderRouter

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


# ---------------------------------------------------------------------------
# parse_synthesis_output: the degradation ladder
# ---------------------------------------------------------------------------


def test_valid_json_object_yields_exact_headline_and_answer() -> None:
    headline, answer = parse_synthesis_output('{"headline": "Owner", "answer": "Dana."}')
    assert (headline, answer) == ("Owner", "Dana.")


def test_json_object_with_blank_headline_falls_back_to_default_headline() -> None:
    """A dict with a real answer but an empty headline uses the fallback
    headline while keeping the answer (line 72 `or FALLBACK_HEADLINE`)."""
    headline, answer = parse_synthesis_output('{"headline": "   ", "answer": "Body."}')
    assert headline == FALLBACK_HEADLINE
    assert answer == "Body."


def test_non_json_single_line_becomes_answer_under_fallback_headline() -> None:
    """Not JSON at all + no newline -> the whole text is the answer under the
    fallback headline (JSONDecodeError branch + the no-rest branch)."""
    headline, answer = parse_synthesis_output("just a plain sentence, no json")
    assert headline == FALLBACK_HEADLINE
    assert answer == "just a plain sentence, no json"


def test_non_json_multiline_uses_first_line_as_headline() -> None:
    """A short first line + a body -> first line is the headline, rest the
    answer (the len(first_line) <= 80 branch)."""
    headline, answer = parse_synthesis_output("Short headline\nThe detailed body follows here.")
    assert headline == "Short headline"
    assert answer == "The detailed body follows here."


def test_first_line_headline_boundary_at_80_chars() -> None:
    """Exactly 80 chars is accepted as a headline; 81 is too long and the
    whole text degrades to the fallback (on / just-over the cutoff)."""
    line80 = "H" * 80
    line81 = "H" * 81
    headline_ok, answer_ok = parse_synthesis_output(f"{line80}\nbody")
    assert headline_ok == line80 and answer_ok == "body"

    headline_over, answer_over = parse_synthesis_output(f"{line81}\nbody")
    assert headline_over == FALLBACK_HEADLINE
    assert answer_over == f"{line81}\nbody"  # untouched whole text


def test_json_array_is_not_a_dict_and_degrades_to_text() -> None:
    """Valid JSON that is a list (not an object) skips the dict branch and
    degrades through the text ladder."""
    headline, answer = parse_synthesis_output('["not", "an", "object"]')
    assert headline == FALLBACK_HEADLINE
    assert answer == '["not", "an", "object"]'


def test_json_object_missing_answer_field_degrades_to_text() -> None:
    """A dict without a valid string `answer` falls through to the text ladder
    rather than returning a half-formed answer."""
    raw = '{"headline": "H"}'
    headline, answer = parse_synthesis_output(raw)
    assert headline == FALLBACK_HEADLINE  # single line, no rest -> fallback
    assert answer == raw


# ---------------------------------------------------------------------------
# AskAnswerGateway.answer: the real per-query lifecycle, empty index
# ---------------------------------------------------------------------------


class _RouterMustNotBeCalled:
    """Fail-honest guard: on empty retrieval NO provider call may happen."""

    async def route(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("router must not be called when retrieval is empty")


def _no_call_router_factory(recorder: Any) -> ProviderRouter:
    # cast: the fake satisfies the structural router seam; on empty retrieval
    # its route() is never reached, so no real provider wiring is needed.
    return cast(ProviderRouter, _RouterMustNotBeCalled())


async def test_gateway_answer_on_empty_index_is_honest_with_no_provider_call(
    tmp_path: Path,
) -> None:
    """The real gateway migrates a fresh DB, retrieves nothing (BM25-only over
    an empty index), and returns the canonical honest answer WITHOUT ever
    invoking the router — the model can only ever see real context."""
    router_built: list[bool] = []

    def router_factory(recorder: Any) -> ProviderRouter:
        router_built.append(True)  # the factory is exercised per query...
        return cast(ProviderRouter, _RouterMustNotBeCalled())

    gateway = AskAnswerGateway(
        db_path=tmp_path / "engine.db",
        migrations_dir=MIGRATIONS_DIR,
        router_factory=router_factory,
    )
    answer = await gateway.answer("who owns the Q3 budget?")

    assert answer.no_answer is True
    assert answer.answer_md == NO_ANSWER_TEXT  # canonical honest copy
    assert answer.citations == ()  # nothing retrieved -> nothing to cite
    assert answer.latency.synthesis_ms == 0  # synthesis never ran
    assert router_built == [True]  # router was built, just never called


async def test_gateway_reuses_migrated_db_across_two_queries(tmp_path: Path) -> None:
    """A second query over the same DB path re-opens its own connection and
    still answers honestly — the per-query lifecycle is repeatable."""
    gateway = AskAnswerGateway(
        db_path=tmp_path / "engine.db",
        migrations_dir=MIGRATIONS_DIR,
        router_factory=_no_call_router_factory,
    )
    first = await gateway.answer("anything at all")
    second = await gateway.answer("something else entirely")
    assert first.no_answer is True and second.no_answer is True


def test_default_router_factory_builds_a_real_provider_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default factory wires a real ProviderRouter (keyless here, so no
    provider is callable) bound to the given ledger recorder."""
    import engine.ask.ask_query_command_dispatcher as dispatcher_module

    # Keep construction inert and deterministic: no disk key read.
    monkeypatch.setattr(dispatcher_module, "build_provider_clients", lambda store: {})

    async def recorder(entry: Any) -> None:
        return None

    router = _default_ask_router_factory(recorder)
    assert isinstance(router, ProviderRouter)
