"""INJECT disposition + the raw-retention property, end to end.

Proves the Wispr-Flow-beating finalizer contract:
- ``inject_requested`` yields INJECT mode: cleaned text for the shell to
  paste, NO note written, NO intent recorded, raw retained;
- the wake word ALWAYS beats the inject hint (a command is never pasted);
- router down mid-inject -> the raw text still lands (as cleaned_text);
- NOTE mode stores the cleaned body with the raw transcript byte-identical
  in the note (seeded property sweep, repo style);
- ``flush_ms`` passes through, and the ``dictation.final`` payload carries
  the additive cleanup/speed fields exactly.
"""

import json
import random
import string
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.dictation.dictation_finalization import DictationReleaseFinalizer
from engine.dictation.dictation_mode_splitter import DictationMode
from engine.dictation.dictation_protocol_names import build_dictation_final_payload
from engine.dictation.personal_dictionary import PersonalDictionary
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
)
from engine.router.router_errors import RouterUnavailableError
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

FIXED_NOW = datetime(2026, 7, 6, 16, 45, tzinfo=UTC)


class FakeRoute:
    """Scripted per-task completions; tasks absent from the script RAISE
    (models a partially-down router)."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def __call__(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        self.calls.append(task_type)
        if task_type not in self._responses:
            raise RouterUnavailableError(task_type, ())
        return RoutedCompletion(
            completion=ProviderCompletion(
                text=self._responses[task_type],
                provider=Provider.GROQ,
                model="llama-3.3-70b-versatile",
                prompt_tokens=10,
                completion_tokens=5,
            ),
            provider=Provider.GROQ,
            model="llama-3.3-70b-versatile",
            latency_ms=250,
        )


def _finalizer(
    vault: Path,
    route: FakeRoute,
    *,
    forbid_intents_db: bool = False,
    tmp_db_path: Path | None = None,
    migrations_dir: Path | None = None,
) -> DictationReleaseFinalizer:
    async def forbidden_factory() -> aiosqlite.Connection:
        raise AssertionError("this flow must never open the intents database")

    async def real_factory() -> aiosqlite.Connection:
        assert tmp_db_path is not None and migrations_dir is not None
        await apply_migrations(tmp_db_path, migrations_dir)
        return await open_sqlite_connection(tmp_db_path)

    return DictationReleaseFinalizer(
        route=route,
        intents_connection_factory=forbidden_factory if forbid_intents_db else real_factory,
        vault_root_provider=lambda: vault,
        indexer=None,
        now=lambda: FIXED_NOW,
        dictionary=PersonalDictionary(path=vault / "no-dictionary.txt"),
    )


# ---------------------------------------------------------------------------
# INJECT mode
# ---------------------------------------------------------------------------


async def test_inject_returns_cleaned_text_and_touches_nothing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    raw = "um send the report to Sanjay no wait to Priya by friday"
    cleaned = "Send the report to Priya by Friday."
    route = FakeRoute({"dictation_cleanup": json.dumps({"cleaned": cleaned})})
    finalizer = _finalizer(vault, route, forbid_intents_db=True)

    result = await finalizer.finalize(raw, inject_requested=True, flush_ms=143)

    assert result.mode is DictationMode.INJECT
    assert result.text == raw  # RAW retained — ground truth, always
    assert result.cleaned_text == cleaned
    assert result.cleanup_source == "model"
    assert result.cleanup_latency_ms == 250
    assert result.flush_ms == 143
    assert result.note_path is None and result.intent is None
    assert route.calls == ["dictation_cleanup"]  # no title call: no note
    assert list(vault.iterdir()) == []  # inject writes NOTHING to the vault


async def test_wake_word_beats_the_inject_hint(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    """'Omni, ...' with an external app focused must still be a COMMAND —
    pasting a command into a random text field would be a misfire."""
    vault = tmp_path / "vault"
    vault.mkdir()
    intent = json.dumps(
        {"intent_type": "create_event", "fields": {"title": "sync"}, "confidence": 0.9}
    )
    route = FakeRoute({"intent_parsing": intent})
    finalizer = _finalizer(
        vault, route, tmp_db_path=tmp_db_path, migrations_dir=real_migrations_dir
    )

    result = await finalizer.finalize("Omni, schedule a sync", inject_requested=True)

    assert result.mode is DictationMode.COMMAND
    assert result.cleaned_text is None  # commands are parsed verbatim, not cleaned
    assert route.calls == ["intent_parsing"]


async def test_inject_with_router_down_lands_the_raw_words(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    raw = "these exact words must land"
    finalizer = _finalizer(vault, FakeRoute({}), forbid_intents_db=True)

    result = await finalizer.finalize(raw, inject_requested=True)

    assert result.mode is DictationMode.INJECT
    assert result.cleaned_text == raw  # raw fallback: never fail the user's words
    assert result.cleanup_source == "raw_fallback"
    assert result.degraded_reason is not None


async def test_empty_release_with_inject_hint_stays_honest(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    finalizer = _finalizer(vault, FakeRoute({}), forbid_intents_db=True)
    result = await finalizer.finalize("   ", inject_requested=True)
    assert result.degraded_reason == "no speech captured before release"
    assert result.cleaned_text is None  # nothing to paste, honestly absent


# ---------------------------------------------------------------------------
# Raw-retention property: raw is ALWAYS present and byte-identical
# ---------------------------------------------------------------------------


def _random_utterance(rng: random.Random) -> str:
    words = []
    for _ in range(rng.randint(1, 18)):
        alphabet = rng.choice(
            [string.ascii_lowercase, "äöüßéñ", "日本語", string.digits]
        )
        words.append("".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8))))
    return " ".join(words)


async def test_property_raw_always_present_and_byte_identical(tmp_path: Path) -> None:
    """Seeded sweep over NOTE + INJECT with a model that half-cleans: in
    every outcome ``result.text`` is the raw input byte-identical, and in
    NOTE mode the raw is retrievable byte-identical from the note file."""
    rng = random.Random(20260706)
    vault = tmp_path / "vault"
    vault.mkdir()
    for i in range(60):
        raw = _random_utterance(rng)
        # A faithful "cleanup": drop trailing words (subset -> guard passes).
        kept = raw.split()[: max(1, len(raw.split()) // 2)]
        cleaned = " ".join(kept)
        route = FakeRoute(
            {
                "dictation_cleanup": json.dumps({"cleaned": cleaned}),
                "live_extraction": json.dumps({"title": f"Sweep {i}"}),
            }
        )
        finalizer = _finalizer(vault, route, forbid_intents_db=True)
        inject_result = await finalizer.finalize(raw, inject_requested=True)
        assert inject_result.text == raw  # byte-identical, always
        note_result = await finalizer.finalize(raw)
        assert note_result.text == raw
        assert note_result.note_path is not None
        content = Path(note_result.note_path).read_text(encoding="utf-8")
        assert raw in content  # raw retrievable byte-identical from the note
        if cleaned != raw:
            assert "Raw transcript" in content  # collapsed section present


async def test_note_body_is_cleaned_and_raw_lives_in_collapsed_section(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    raw = "um okay so the plan is uh ship on friday"
    cleaned = "The plan is: ship on Friday."
    route = FakeRoute(
        {
            "dictation_cleanup": json.dumps({"cleaned": cleaned}),
            "live_extraction": json.dumps({"title": "Ship plan"}),
        }
    )
    finalizer = _finalizer(vault, route, forbid_intents_db=True)
    result = await finalizer.finalize(raw)
    assert result.note_path is not None
    content = Path(result.note_path).read_text(encoding="utf-8")
    # Cleaned body appears BEFORE the collapsed raw section.
    assert content.index(cleaned) < content.index("<details>")
    assert f"<details><summary>Raw transcript</summary>\n\n{raw}\n\n</details>" in content


async def test_note_with_identity_cleanup_has_no_redundant_raw_section(
    tmp_path: Path,
) -> None:
    """When cleanup falls back (cleaned == raw), duplicating the text in a
    collapsed section would be noise — the body IS the raw text."""
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({"live_extraction": json.dumps({"title": "Raw note"})})
    finalizer = _finalizer(vault, route, forbid_intents_db=True)
    result = await finalizer.finalize("verbatim words kept as body")
    assert result.note_path is not None
    content = Path(result.note_path).read_text(encoding="utf-8")
    assert "verbatim words kept as body" in content
    assert "<details>" not in content


# ---------------------------------------------------------------------------
# dictation.final payload: additive fields, exact
# ---------------------------------------------------------------------------


async def test_final_payload_carries_cleanup_and_speed_fields(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    raw = "um ship it on friday"
    cleaned = "Ship it on Friday."
    route = FakeRoute({"dictation_cleanup": json.dumps({"cleaned": cleaned})})
    finalizer = _finalizer(vault, route, forbid_intents_db=True)
    result = await finalizer.finalize(raw, inject_requested=True, flush_ms=88)

    payload = build_dictation_final_payload(result)
    assert payload["mode"] == "inject"
    assert payload["text"] == raw
    assert payload["cleaned_text"] == cleaned
    assert payload["cleanup_source"] == "model"
    assert payload["cleanup_latency_ms"] == 250
    assert payload["flush_ms"] == 88
    assert "note_path" not in payload and "intent" not in payload


async def test_final_payload_omits_absent_optionals(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    finalizer = _finalizer(vault, FakeRoute({}), forbid_intents_db=True)
    result = await finalizer.finalize("  ")
    payload = build_dictation_final_payload(result)
    assert "cleaned_text" not in payload
    assert "cleanup_source" not in payload
    assert "flush_ms" not in payload
