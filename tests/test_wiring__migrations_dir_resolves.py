"""Regression: the production MIGRATIONS_DIR must point at the real migrations.

The default service factories resolve the migrations directory RELATIVE to
their own file. When wiring modules moved under ``engine/wiring/`` the parent
count silently pointed one directory too shallow (``engine/migrations``, which
does not exist), so every table-creating boot failed closed with
``no such table`` — invisible to the suite because every test injects a
migrations dir. This pins the real resolution so the gap cannot reopen.
"""

from engine.wiring.server_default_service_factories import MIGRATIONS_DIR


def test_migrations_dir_exists_and_holds_the_schema() -> None:
    assert MIGRATIONS_DIR.is_dir(), f"{MIGRATIONS_DIR} does not exist"
    names = {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
    # The initial schema and the M7 app_settings migration must both be found
    # by the production factories, not just by tests that inject a path.
    assert "0001_initial.sql" in names
    assert "0009_app_settings.sql" in names
