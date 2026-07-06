"""Vault-root resolution and standard vault subfolders.

Purpose: the single place the vault location comes from. For now the root
is read from the ``OMNI_VAULT_DIR`` environment variable (settings-service
integration lands later); writers take an explicit ``vault_root`` so tests
use ``tmp_path`` synthetic vaults only.
Pipeline position: called by every writer in ``engine.vault``.

Security invariant: fail closed — if the vault is not configured or the
path is not an existing directory, raise instead of guessing a location
(never write the user's notes to a surprise directory).
"""

import os
from pathlib import Path

from engine.vault.vault_errors import VaultNotConfiguredError

# Standard vault subfolders, in pipeline order. The daily folder is a
# default only — the appender accepts a per-call override (configurable).
MEETINGS_FOLDER = "Meetings"
PEOPLE_FOLDER = "People"
INBOX_FOLDER = "Inbox"
DAILY_FOLDER = "Daily"

# Env var carrying the absolute vault path until settings integration.
VAULT_DIR_ENV_VAR = "OMNI_VAULT_DIR"


def resolve_vault_root() -> Path:
    """Resolve the vault root from ``OMNI_VAULT_DIR``.

    Returns the vault root as a ``Path``.
    Raises ``VaultNotConfiguredError`` if the variable is unset/blank or
    does not name an existing directory (fail closed: never invent a vault).
    """
    raw = os.environ.get(VAULT_DIR_ENV_VAR, "").strip()
    if not raw:
        # fail-closed: no configured vault, no writes.
        raise VaultNotConfiguredError(
            f"{VAULT_DIR_ENV_VAR} is not set; refusing to write vault files"
        )
    root = Path(raw)
    if not root.is_dir():
        # fail-closed: a mistyped path must not silently become a new vault.
        raise VaultNotConfiguredError(
            f"{VAULT_DIR_ENV_VAR} does not point at an existing directory: {root}"
        )
    return root


def ensure_vault_subfolder(vault_root: Path, folder_name: str) -> Path:
    """Return ``vault_root/folder_name``, creating it (parents included) if absent.

    Creating folders is always safe under the information boundary: it adds,
    never edits.
    """
    folder = vault_root / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    return folder
