"""Omni engine security package: key custody, redaction, and the kill switch.

Purpose: the single home for security-critical primitives that other engine
packages consume but never reimplement — DPAPI-encrypted API-key storage,
secret redaction, and the global egress kill switch.
Pipeline position: below every feature package. ``engine.router`` asks this
package for provider *clients'* key material via :class:`ProviderKeyStore`
(keys never travel further), and consults :func:`kill_switch_engaged` before
any external call.

Security invariants upheld package-wide (claude.md §5.6 project bindings):
- Keys are DPAPI-encrypted per-user at rest; plaintext never touches disk.
- Key material is never logged and is redacted from every repr/error string.
- The kill switch fails CLOSED: ambiguous configuration means egress refused.
"""

from engine.security.dpapi_windows_crypto import (
    DpapiOperationError,
    DpapiUnavailableError,
    dpapi_protect,
    dpapi_unprotect,
)
from engine.security.kill_switch import (
    KILL_SWITCH_ENV_VAR,
    kill_switch_engaged,
    set_kill_switch_runtime_override,
)
from engine.security.provider_key_store import ProviderKeyStore, default_key_store_path
from engine.security.secret_redaction import (
    REDACTION_PLACEHOLDER,
    SecretApiKey,
    redact_secret_material,
)

__all__ = [
    "KILL_SWITCH_ENV_VAR",
    "REDACTION_PLACEHOLDER",
    "DpapiOperationError",
    "DpapiUnavailableError",
    "ProviderKeyStore",
    "SecretApiKey",
    "default_key_store_path",
    "dpapi_protect",
    "dpapi_unprotect",
    "kill_switch_engaged",
    "redact_secret_material",
    "set_kill_switch_runtime_override",
]
