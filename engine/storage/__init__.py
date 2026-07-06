"""SQLite storage layer for the engine.

Purpose: owns the on-disk database — connection opening and the
migrations runner. Nothing else in the engine touches SQLite directly.
Pipeline position: beneath every feature module; meetings, transcript
segments, and the audit log all persist through here.

Security invariants:
- The database lives in the user's private profile
  (%LOCALAPPDATA%/Omni/omni.db by default) — never a shared path.
- The audit log is append-only, enforced IN THE SCHEMA by RAISE(ABORT)
  triggers (see migrations/0001_initial.sql), not by code convention.
"""

from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations, list_applied_migrations

__all__ = [
    "apply_migrations",
    "list_applied_migrations",
    "open_sqlite_connection",
]
