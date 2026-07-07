"""Naomi voice answer service: honest no-answer, cited synthesis, safe TTS.

Adversarial intent:
- FAIL HONEST: empty/below-floor retrieval must return the exact refusal with
  ZERO provider calls (a provider that gets called on empty context is a leak
  of the honesty invariant).
- The affect tag and the [n] citation markers must be peeled off the SPOKEN
  text (Cartesia must never read "<<affect...>>" or "one, two" aloud), while
  the citation markers still map 1:1 onto the retrieved chunks for the chips.
- A model that itself reports no-answer yields no_answer=True with no citations.
"""

import pytest

from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.naomi import naomi_voice_answer_service as svc_module
from engine.naomi.naomi_voice_answer_service import NaomiVoiceAnswerService
from engine.naomi.naomi_voice_synthesis_prompt import NAOMI_NO_ANSWER_TEXT
from engine.router.completion_contract import (
    Provider,
    ProviderCompletion,
    RoutedCompletion,
)

CHUNK = RetrievedChunk(
    chunk_id=1,
    note_path="Clients/Henderson.md",
    source_type="vault",
    note_title="Henderson",
    heading_path="Contract",
    line_start=10,
    line_end=12,
    text="The Henderson contract renewal is due August 15th.",
    contextualized_text="The Henderson contract renewal is due August 15th.",
    score=0.5,
    retrieval_source="hybrid_rrf",
)


class StructuredResult:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.route = "hybrid"


class RecordingRouter:
    """Records route() calls and returns a canned completion."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[object] = []

    async def route(
        self, task_type: str, system_frame: str, messages: object, **kwargs: object
    ) -> RoutedCompletion:
        self.calls.append((task_type, system_frame, messages, kwargs))
        completion = ProviderCompletion(
            text=self.text,
            provider=Provider.GROQ,
            model="test-model",
            prompt_tokens=10,
            completion_tokens=5,
        )
        return RoutedCompletion(
            completion=completion, provider=Provider.GROQ, model="test-model", latency_ms=12
        )


def _patch_retrieval(monkeypatch: pytest.MonkeyPatch, chunks: list[RetrievedChunk]) -> None:
    async def fake_retrieve(*_args: object, **_kwargs: object) -> StructuredResult:
        return StructuredResult(chunks)

    monkeypatch.setattr(svc_module, "retrieve_structured_first", fake_retrieve)


async def test_empty_retrieval_is_honest_no_answer_with_zero_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_retrieval(monkeypatch, [])
    router = RecordingRouter("<<affect v=1 a=1>> should never be used")
    service = NaomiVoiceAnswerService(connection=object(), retriever=object(), router=router)  # type: ignore[arg-type]
    answer = await service.answer("When is the Henderson renewal due?")
    assert answer.no_answer is True
    assert answer.spoken_text == NAOMI_NO_ANSWER_TEXT
    assert answer.affect is None
    assert answer.citations == ()
    assert answer.llm_ms == 0
    assert router.calls == []  # ZERO provider calls on empty context


async def test_synthesis_strips_tag_and_markers_but_maps_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_retrieval(monkeypatch, [CHUNK])
    router = RecordingRouter("<<affect v=0.6 a=0.5>> The renewal is due August 15th [1].")
    service = NaomiVoiceAnswerService(connection=object(), retriever=object(), router=router)  # type: ignore[arg-type]
    answer = await service.answer("When is the Henderson renewal due?")
    assert answer.no_answer is False
    # Spoken text: NO affect tag, NO [n] marker (Cartesia must not read them).
    assert "<<affect" not in answer.spoken_text
    assert "[1]" not in answer.spoken_text
    assert answer.spoken_text == "The renewal is due August 15th."
    # Affect parsed from the tag.
    assert answer.affect is not None
    assert answer.affect.valence == pytest.approx(0.6)
    assert answer.affect.arousal == pytest.approx(0.5)
    # Citation mapped 1:1 onto the retrieved chunk.
    assert len(answer.citations) == 1
    assert answer.citations[0].n == 1
    assert answer.citations[0].note_path == "Clients/Henderson.md"
    assert len(router.calls) == 1


async def test_model_reported_no_answer_yields_no_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_retrieval(monkeypatch, [CHUNK])
    router = RecordingRouter(NAOMI_NO_ANSWER_TEXT)  # model says it's not there
    service = NaomiVoiceAnswerService(connection=object(), retriever=object(), router=router)  # type: ignore[arg-type]
    answer = await service.answer("Something unrelated?")
    assert answer.no_answer is True
    assert answer.spoken_text == NAOMI_NO_ANSWER_TEXT
    assert answer.citations == ()


async def test_invented_marker_is_stripped_and_never_cited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_retrieval(monkeypatch, [CHUNK])
    # The model invents [2] and [3] though only ONE chunk exists.
    router = RecordingRouter("<<affect v=0.2 a=0.3>> It is due soon [1] per the file [2][3].")
    service = NaomiVoiceAnswerService(connection=object(), retriever=object(), router=router)  # type: ignore[arg-type]
    answer = await service.answer("When?")
    assert "[2]" not in answer.spoken_text and "[3]" not in answer.spoken_text
    # Only the real marker maps to a citation; invented ones are dropped.
    assert [c.n for c in answer.citations] == [1]
