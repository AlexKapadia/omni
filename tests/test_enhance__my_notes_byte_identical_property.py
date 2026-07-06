"""Property-style fidelity proof: the user's notes survive finalization byte-identical.

Seeded pseudo-random generation (house style — deterministic, replayable)
builds 30 adversarial notepads: unicode planes, mixed newline conventions,
markdown metacharacters, YAML-lookalikes, zero-width characters, huge lines.
For every one, after a FULL real finalization run: the DB column equals the
input EXACTLY (the fidelity mandate's storage half) and the vault note
carries the input's rstripped form verbatim (creation's only permitted touch
is structural trailing whitespace).
"""

import random
import string
from collections.abc import Callable
from pathlib import Path

from engine.enhance import MeetingFinalizationService
from engine.protocol import EventBroadcastHub
from engine.router import ProviderRouter, RouterError
from engine.router.fallback_executor import LedgerRecorder
from engine.storage.meetings_repository import fetch_meeting_row
from engine.storage.sqlite_connection import open_sqlite_connection
from tests.enhance_test_support import (
    VALID_ENHANCED_MARKDOWN,
    VALID_EXTRACTION_JSON,
    ScriptedRouter,
    seed_meeting,
)

_ALPHABETS = [
    string.ascii_letters + string.digits + " ",
    "абвгдеёжз 你好世界 مرحبا שלום ",
    "🙂🚀🎯💡✅❌ emoji soup ",
    "#*_`[]()>|-=+~ markdown metachars ",
    'key: value\n- "yaml: lookalike"\n--- ',
    "​‌﻿zero width party ",
    "tabs\tand\ttabs ",
]


def _pinned_router_factory(
    router: ProviderRouter,
) -> Callable[[LedgerRecorder], ProviderRouter]:
    """Bind the per-case router via a function boundary (loop-capture safety)."""

    def factory(_recorder: LedgerRecorder) -> ProviderRouter:
        return router

    return factory


def _random_notepad(rng: random.Random) -> str:
    """One adversarial notepad: 1-12 lines drawn from hostile alphabets,
    with newline convention and edge whitespace chosen per-case."""
    lines = []
    for _ in range(rng.randint(1, 12)):
        alphabet = rng.choice(_ALPHABETS)
        lines.append("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 120))))
    newline = rng.choice(["\n", "\r\n"])
    text = newline.join(lines)
    if rng.random() < 0.3:
        text = " \t" + text  # leading whitespace must survive (interior bytes)
    if rng.random() < 0.3:
        text = text + newline  # trailing whitespace: creation may rstrip only
    # The managed-marker sentinel has its own dedicated corruption test —
    # random cases must not accidentally collide with that separate contract.
    return text.replace("omni:managed", "omni_managed")


async def test_thirty_adversarial_notepads_survive_finalization_byte_identical(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    rng = random.Random(20260706)  # seeded: failures replay exactly
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    hub = EventBroadcastHub()

    for case in range(30):
        notepad = _random_notepad(rng)
        meeting_id = f"prop-{case}"
        await seed_meeting(tmp_db_path, real_migrations_dir, meeting_id)
        script: dict[str, list[str | RouterError]] = {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
        router = ScriptedRouter(script)
        service = MeetingFinalizationService(
            db_path=tmp_db_path,
            migrations_dir=real_migrations_dir,
            hub=hub,
            router_factory=_pinned_router_factory(router),
            vault_root_resolver=lambda: vault_root,
        )
        result = await service.finalize(meeting_id, notepad, "general")

        # --- DB half of the mandate: EXACT bytes, all conventions intact.
        connection = await open_sqlite_connection(tmp_db_path)
        try:
            row = await fetch_meeting_row(connection, meeting_id)
        finally:
            await connection.close()
        assert row is not None
        assert row.notes_text == notepad, f"case {case}: DB copy diverged"

        # --- vault half: the note carries the rstripped input verbatim
        # (creation's ONLY touch is structural trailing whitespace).
        content = (vault_root / result.note_path).read_bytes().decode("utf-8")
        expected = notepad.rstrip()
        assert expected in content, f"case {case}: vault copy diverged"
        # Interior newline conventions survive inside the note body too.
        if "\r\n" in expected:
            assert "\r\n" in content, f"case {case}: CRLF was normalised away"
