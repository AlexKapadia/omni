"""Windows DPAPI encrypt/decrypt primitives via ctypes (stdlib only, no deps).

Purpose: the raw byte-level CryptProtectData / CryptUnprotectData calls that
:mod:`engine.security.provider_key_store` builds key custody on. DPAPI keys
are derived from the Windows user's logon credential, so blobs written here
are decryptable only by THIS user on THIS machine — per-user encryption at
rest with zero key-management code of our own.
Pipeline position: lowest layer of ``engine.security``; nothing outside the
security package should call these functions directly.

Security invariants:
- CRYPTPROTECT_UI_FORBIDDEN is always set: DPAPI may never pop UI from a
  headless sidecar (a hung prompt would look like a silent failure).
- Failures raise (fail closed) — no code path returns plaintext on error or
  writes an unencrypted fallback blob.
- Error messages carry only the Win32 error CODE, never payload bytes.
"""

import ctypes
import sys

# DPAPI flag: never show credential UI (headless sidecar invariant).
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DpapiUnavailableError(RuntimeError):
    """Raised when DPAPI is requested on a non-Windows platform."""


class DpapiOperationError(RuntimeError):
    """Raised when CryptProtectData/CryptUnprotectData reports failure."""


if sys.platform == "win32":
    from ctypes import wintypes

    class _DataBlob(ctypes.Structure):
        """Mirror of the Win32 DATA_BLOB struct (crypt32 in/out buffers)."""

        _fields_ = (
            ("cb_data", wintypes.DWORD),
            ("pb_data", ctypes.POINTER(ctypes.c_char)),
        )

    def _run_dpapi_call(function_name: str, payload: bytes) -> bytes:
        """Invoke one crypt32 protect/unprotect call and copy out the result.

        WHY the copy + LocalFree dance: crypt32 allocates the output blob
        with LocalAlloc; we must copy it into Python-owned bytes and free
        the OS allocation or every call leaks.
        """
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        size = len(payload)
        # from_buffer_copy needs size >= 1; a 1-byte scratch backs the
        # (never-dereferenced, cb_data=0) empty-payload case.
        buffer = (
            (ctypes.c_char * size).from_buffer_copy(payload) if size else (ctypes.c_char * 1)()
        )
        blob_in = _DataBlob(size, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DataBlob()
        dpapi_function = getattr(crypt32, function_name)
        succeeded = dpapi_function(
            ctypes.byref(blob_in),
            None,  # description / out-description (unused)
            None,  # optional entropy: none — per-user DPAPI scope suffices
            None,  # reserved
            None,  # prompt struct: None + UI_FORBIDDEN = strictly headless
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
        if not succeeded:
            # Fail closed: surface the Win32 code only — never payload bytes.
            error_code = ctypes.get_last_error() or kernel32.GetLastError()
            raise DpapiOperationError(
                f"{function_name} failed with Win32 error code {error_code}"
            )
        try:
            return ctypes.string_at(blob_out.pb_data, blob_out.cb_data)
        finally:
            kernel32.LocalFree(blob_out.pb_data)

else:

    def _run_dpapi_call(function_name: str, payload: bytes) -> bytes:
        """Non-Windows stub so Linux CI type-checks; always fails closed."""
        raise DpapiUnavailableError("DPAPI is only available on Windows")


def dpapi_protect(plaintext: bytes) -> bytes:
    """Encrypt ``plaintext`` for the current Windows user. Fails closed."""
    if sys.platform != "win32":
        raise DpapiUnavailableError("DPAPI is only available on Windows")
    return _run_dpapi_call("CryptProtectData", plaintext)


def dpapi_unprotect(ciphertext: bytes) -> bytes:
    """Decrypt a blob previously produced by :func:`dpapi_protect`.

    Raises :class:`DpapiOperationError` on tampered/corrupt blobs or blobs
    encrypted by a different user — never returns garbage bytes.
    """
    if sys.platform != "win32":
        raise DpapiUnavailableError("DPAPI is only available on Windows")
    return _run_dpapi_call("CryptUnprotectData", ciphertext)
