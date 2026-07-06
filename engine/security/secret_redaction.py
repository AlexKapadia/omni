"""Secret wrapper type and redaction helpers for API-key material.

Purpose: make it structurally hard to leak a key. Keys travel through the
engine only as :class:`SecretApiKey` — whose ``repr``/``str`` never reveal
the value — and every error/log string that could have absorbed key material
(e.g. an SDK exception echoing a header) is scrubbed with
:func:`redact_secret_material` before it propagates.
Pipeline position: used by ``engine.security.provider_key_store`` (custody)
and by every ``engine.router`` provider client (error paths).

Security invariant: key material never appears in logs, reprs, exception
messages, or ledger rows (claude.md §5.6 — secrets never in logs).
"""

from collections.abc import Iterable

# What leaked secret material is replaced with, everywhere, uniformly.
REDACTION_PLACEHOLDER = "[REDACTED]"

# Below this length a "secret" is more likely a fragment that would cause
# runaway replacement (e.g. redacting every "a" in a message); real provider
# keys are far longer. Short values are still redacted when exactly matched.
_MIN_SUBSTRING_REDACTION_LENGTH = 6


class SecretApiKey:
    """An API key that refuses to disclose itself accidentally.

    The raw value is available ONLY via :meth:`reveal`, which exists so a
    provider client can hand the key to its SDK constructor — the single
    legitimate consumer. Everything else (repr, str, f-strings, logging,
    debuggers printing locals) sees the redaction placeholder.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not value:
            # Fail closed: an empty key is a configuration error, not a key.
            raise ValueError("SecretApiKey requires a non-empty value")
        self._value = value

    def reveal(self) -> str:
        """Return the raw key. Call sites must pass it ONLY to an SDK client."""
        return self._value

    def __repr__(self) -> str:
        # Redaction invariant: never include self._value.
        return f"SecretApiKey({REDACTION_PLACEHOLDER})"

    def __str__(self) -> str:
        # Redaction invariant: f-string interpolation must not leak either.
        return REDACTION_PLACEHOLDER

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretApiKey):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)


def redact_secret_material(text: str, secrets: Iterable[SecretApiKey]) -> str:
    """Scrub every secret's raw value out of ``text``.

    Applied to any string built from data an SDK or OS call produced (error
    messages, response reprs) before that string is raised, logged, or
    stored. Exact-match replacement only — no regex, so no pattern can be
    tricked into leaving a partial key behind while claiming success.
    """
    scrubbed = text
    for secret in secrets:
        raw = secret.reveal()
        if len(raw) >= _MIN_SUBSTRING_REDACTION_LENGTH:
            scrubbed = scrubbed.replace(raw, REDACTION_PLACEHOLDER)
        elif scrubbed == raw:
            scrubbed = REDACTION_PLACEHOLDER
    return scrubbed
