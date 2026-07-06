"""Exception types for the vault-writer package.

Purpose: one place defining every way a vault write can be refused, so
callers (and tests) can distinguish "refused to protect user content"
(fail closed) from ordinary I/O failure.
Pipeline position: imported by every ``engine.vault`` module.

Security invariant: these exceptions ARE the fail-closed mechanism — a
refused write raises before any byte reaches the target file.
"""


class VaultWriteError(Exception):
    """Base class: a vault write was refused or failed. File left untouched."""


class VaultNotConfiguredError(VaultWriteError):
    """OMNI_VAULT_DIR is unset/empty or not an existing directory (fail closed)."""


class ManagedRegionCorruptionError(VaultWriteError):
    """Managed-region markers are missing, duplicated, nested, or out of order.

    Raised BEFORE writing: rewriting an ambiguous region could destroy
    user-authored text, so the write is refused (fail closed).
    """


class FrontmatterFormatError(VaultWriteError):
    """Frontmatter could not be emitted or parsed under the narrow Omni schema."""


class VaultFileLockedError(VaultWriteError):
    """The target stayed locked by another process (e.g. sync client) after retries.

    The original file is intact and the temp file has been removed.
    """
