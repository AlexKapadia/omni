"""``keys.save`` / ``keys.validate`` gateway + WS dispatch.

Purpose: the server-layer surface for provider API-key custody used by the
onboarding wizard and Settings — save one key (masked input -> DPAPI
:class:`ProviderKeyStore`), and validate the STORED key with one real,
minimal call (:func:`validate_provider_key`).
Pipeline position: driven by the connection handler for any command whose
name is in ``KEYS_COMMAND_NAMES``; speaks only ``engine.protocol`` shapes.

Security invariants (claude.md §5.6 DPAPI binding):
- Key material rides in only ONE direction (client -> store) and only on
  ``keys.save``; it is wrapped in :class:`SecretApiKey` the instant it
  leaves the payload and is never echoed, logged, or reflected back.
- ``keys.validate`` never carries a key value — it probes the STORED key,
  so a reply can never leak one; validation honours the kill switch
  (fail closed on egress).
- Strict payload validation (extra fields forbidden) — deny by default.
"""

import logging
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.protocol import (
    COMMAND_KEYS_SAVE,
    COMMAND_KEYS_VALIDATE,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    KeysSaveCommandPayload,
    KeysValidateCommandPayload,
    ProtocolErrorCode,
    error_reply,
)
from engine.security.provider_key_store import ProviderKeyStore
from engine.security.secret_redaction import SecretApiKey
from engine.wiring.provider_key_live_validation import validate_provider_key

logger = logging.getLogger(__name__)

# The commands this dispatcher owns; the handler routes ONLY these here.
KEYS_COMMAND_NAMES = frozenset({COMMAND_KEYS_SAVE, COMMAND_KEYS_VALIDATE})

# Additive error code (string literal beside the pinned enum, mirroring the
# settings dispatcher's ``settings_error``).
KEYS_ERROR_CODE = "keys_error"

SendFn = Callable[[Envelope], Awaitable[None]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=payload
    )


def _keys_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": KEYS_ERROR_CODE, "message": message},
    )


class ProviderKeysCommandGateway:
    """One per engine process; construction is inert (no I/O, no keys read).

    The store is resolved per command so a fresh key is visible immediately
    to the very next validate without any process-level caching.
    """

    def __init__(self, key_store: ProviderKeyStore | None = None) -> None:
        self._key_store = key_store if key_store is not None else ProviderKeyStore()

    def save_key(self, provider: str, secret: str) -> None:
        """Persist one provider key, DPAPI-encrypted. Plaintext exists only
        for the instant it is wrapped in :class:`SecretApiKey`."""
        # local-only invariant: the key lands in the per-user DPAPI blob only.
        self._key_store.set_key(provider, SecretApiKey(secret))

    async def validate_key(self, provider: str) -> dict[str, object]:
        """Validate the STORED key with one real, minimal call (honest result)."""
        result = await validate_provider_key(provider, self._key_store)
        return {
            "provider": result.provider,
            "valid": result.valid,
            "message": result.message,
            "latency_ms": result.latency_ms,
        }


async def dispatch_keys_command(
    command: Envelope, gateway: ProviderKeysCommandGateway | None, send: SendFn
) -> None:
    """Handle one validated keys.* command, always replying (fail closed)."""
    if gateway is None:
        # Key custody not wired in this app instance: refuse honestly.
        await send(_keys_error_reply(command.id, "key custody is not available"))
        return
    try:
        if command.name == COMMAND_KEYS_SAVE:
            payload = KeysSaveCommandPayload.model_validate(command.payload)
        else:
            validate_payload = KeysValidateCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                f"{command.name} payload failed validation",
            )
        )
        return

    if command.name == COMMAND_KEYS_SAVE:
        try:
            # get_secret_value() is the only read of the plaintext; it is not
            # logged and does not appear in any reply.
            gateway.save_key(payload.provider, payload.key.get_secret_value())
        except Exception:
            # No exception text: it could conceivably carry key-adjacent data.
            logger.exception("keys.save failed")
            await send(_keys_error_reply(command.id, "the key could not be saved"))
            return
        await send(_ok_reply(command.id, {"ok": True, "provider": payload.provider}))
        return

    try:
        result = await gateway.validate_key(validate_payload.provider)
    except Exception:
        logger.exception("keys.validate failed")
        await send(_keys_error_reply(command.id, "the key could not be validated"))
        return
    await send(_ok_reply(command.id, result))
