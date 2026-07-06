"""Meeting library reads after finalization: list/get serve the real rows.

The REAL service against real migrations and a real tmp vault. Proves the
library surface (``list_meetings`` / ``get_meeting``) serves the finalized
meeting with its verbatim notes and ordered transcript segments, and that a
missing meeting reads honestly as None.
"""

from pathlib import Path

from tests.enhance_test_support import (
    NOTEPAD,
    VALID_ENHANCED_MARKDOWN,
    VALID_EXTRACTION_JSON,
    ScriptedRouter,
    make_finalization_service,
    seed_meeting,
)


async def test_list_and_get_serve_the_finalized_meeting(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-10")
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_finalization_service(tmp_db_path, real_migrations_dir, vault_root, router)
    await service.finalize("m-10", NOTEPAD, "general")

    rows = await service.list_meetings()
    assert [row.id for row in rows] == ["m-10"]
    found = await service.get_meeting("m-10")
    assert found is not None
    row, segments = found
    assert row.notes_text == NOTEPAD
    assert [s.stream for s in segments] == ["them", "me", "them", "me"]
    assert await service.get_meeting("ghost") is None
