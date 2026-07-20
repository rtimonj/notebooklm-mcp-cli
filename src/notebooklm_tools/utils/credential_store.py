"""Encryption-at-rest for credential files (cookies.json, metadata.json, auth.json).

Credentials are encrypted with Fernet (symmetric, authenticated) using a key
stored in the system keyring (Secret Service / GNOME Keyring on Linux, Keychain
on macOS, Credential Locker on Windows).

On-disk format is a JSON "envelope" so file names and extensions stay the same
and mtime-based invalidation (``get_active_auth_mtime``) keeps working:

    {"__nlm_encrypted__": 1, "ciphertext": "<fernet token>"}

Fallback behavior when no keyring is available (e.g. SSH session without DBus):
writes stay plaintext and a warning is logged ONCE per process — never a silent
downgrade. Reading an encrypted file without keyring access raises
``CredentialStoreError`` with a actionable message.

Set ``NOTEBOOKLM_DISABLE_ENCRYPTION=1`` to force plaintext storage (used by the
test suite to avoid touching the developer's real keyring).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "notebooklm-mcp-cli"
KEYRING_KEY_NAME = "credentials-encryption-key"
ENVELOPE_MARKER = "__nlm_encrypted__"
DISABLE_ENCRYPTION_ENV = "NOTEBOOKLM_DISABLE_ENCRYPTION"

# Module-level caches: keyring lookups go over DBus, so avoid one roundtrip
# per credential read. reset_cache() restores a clean state for tests.
_cached_key: bytes | None = None
_key_lookup_done = False
_plaintext_warning_emitted = False

# Serializes first-use key generation so concurrent callers (the MCP server is
# multi-threaded) cannot each generate a different key and clobber each other's
# in the keyring, which would orphan files encrypted with the losing key.
_key_lock = threading.Lock()


class CredentialStoreError(Exception):
    """Raised when an encrypted credential file cannot be decrypted."""


def _require_encryption() -> bool:
    """Whether credential writes must fail closed when no keyring key exists.

    Sourced from config (``auth.require_encryption``), which already applies the
    NLM_REQUIRE_ENCRYPTION env override. Defaults to False on any lookup error
    so a broken config never blocks the credential path unexpectedly.
    """
    try:
        from notebooklm_tools.utils.config import get_config

        return bool(get_config().auth.require_encryption)
    except Exception:
        return False


def plaintext_fallback_active() -> bool:
    """True when credentials would currently be written in plaintext.

    That is: encryption is not explicitly disabled, yet no keyring key is
    available. Used to surface a visible warning at MCP server startup.
    """
    if os.environ.get(DISABLE_ENCRYPTION_ENV):
        return False  # user explicitly opted out; not an unexpected downgrade
    return get_encryption_key() is None


def reset_cache() -> None:
    """Reset cached key and warning state (for tests)."""
    global _cached_key, _key_lookup_done, _plaintext_warning_emitted
    _cached_key = None
    _key_lookup_done = False
    _plaintext_warning_emitted = False


def get_encryption_key() -> bytes | None:
    """Return the Fernet key from the system keyring, creating it on first use.

    Returns None when the keyring is unavailable (no DBus, no backend) or
    encryption is explicitly disabled via NOTEBOOKLM_DISABLE_ENCRYPTION.
    """
    global _cached_key, _key_lookup_done

    if os.environ.get(DISABLE_ENCRYPTION_ENV):
        return None

    # Fast path: lookup already done, no lock needed.
    if _key_lookup_done:
        return _cached_key

    # Slow path: serialize under the lock and re-check. Double-checked locking
    # so only one thread ever generates/stores a key; the rest reuse it.
    with _key_lock:
        if _key_lookup_done:
            return _cached_key

        try:
            import keyring
            from cryptography.fernet import Fernet

            # Re-read the keyring inside the lock before generating: if another
            # thread (or process) already stored a key, adopt it instead of
            # overwriting it with a fresh one.
            stored = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY_NAME)
            if stored:
                _cached_key = stored.encode("ascii")
            else:
                new_key = Fernet.generate_key()
                keyring.set_password(KEYRING_SERVICE, KEYRING_KEY_NAME, new_key.decode("ascii"))
                _cached_key = new_key
                logger.info("Generated new credential encryption key in system keyring")
        except Exception as e:
            logger.debug(f"System keyring unavailable: {type(e).__name__}: {e}")
            _cached_key = None

        _key_lookup_done = True
        return _cached_key


def is_encrypted(data: Any) -> bool:
    """Return True if the parsed JSON object is an encryption envelope."""
    return isinstance(data, dict) and data.get(ENVELOPE_MARKER) == 1


def encrypt_payload(obj: Any, key: bytes) -> dict[str, Any]:
    """Encrypt a JSON-serializable object into an envelope dict."""
    from cryptography.fernet import Fernet

    token = Fernet(key).encrypt(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    return {ENVELOPE_MARKER: 1, "ciphertext": token.decode("ascii")}


def decrypt_payload(envelope: dict[str, Any], key: bytes) -> Any:
    """Decrypt an envelope dict back into the original object.

    Raises CredentialStoreError on tampered/corrupted ciphertext or wrong key.
    """
    from cryptography.fernet import Fernet, InvalidToken

    try:
        plaintext = Fernet(key).decrypt(envelope["ciphertext"].encode("ascii"))
        return json.loads(plaintext.decode("utf-8"))
    except (InvalidToken, KeyError, ValueError) as e:
        raise CredentialStoreError(
            "Failed to decrypt credential file (corrupted data or wrong encryption key). "
            "Re-authenticate with 'nlm login' to regenerate credentials."
        ) from e


def _warn_plaintext_once() -> None:
    global _plaintext_warning_emitted
    if not _plaintext_warning_emitted:
        _plaintext_warning_emitted = True
        if os.environ.get(DISABLE_ENCRYPTION_ENV):
            logger.info(
                f"Credential encryption disabled via {DISABLE_ENCRYPTION_ENV}; "
                "storing credentials in plaintext."
            )
        else:
            logger.warning(
                "Credentials stored in PLAINTEXT: system keyring unavailable "
                "(no Secret Service/DBus session?). Anyone with read access to "
                "~/.notebooklm-mcp-cli can use your Google session cookies."
            )


def write_secure_json(path: Path, obj: Any) -> None:
    """Write a JSON file, encrypted when a keyring-backed key is available.

    The write is atomic: content goes to a sibling temp file created 0o600 with
    O_EXCL, then os.replace() swaps it into place. A crash mid-write therefore
    never leaves a truncated or partially written credential file — readers see
    either the old file or the fully written new one.

    Falls back to plaintext with a loud (once-per-process) warning when no key
    is available.

    Note: for the plaintext-to-encrypted migration, the previous cleartext file
    is unlinked by os.replace, but its on-disk blocks may remain recoverable on
    SSDs and journaling/copy-on-write filesystems. True secure erase is not
    achievable from user space there; this is a known, accepted limitation.
    """
    key = get_encryption_key()
    if key is not None:
        payload: Any = encrypt_payload(obj, key)
    elif _require_encryption():
        # Fail closed: never silently downgrade to plaintext when the operator
        # has demanded encryption.
        raise CredentialStoreError(
            f"Encryption is required (auth.require_encryption / {DISABLE_ENCRYPTION_ENV} "
            "unset) but the system keyring is unavailable, so credentials were NOT "
            "written. Run from a desktop session with a working keyring, or unset "
            "require_encryption to allow plaintext storage."
        )
    else:
        _warn_plaintext_once()
        payload = obj

    # Unique per-thread/process temp name so O_EXCL never collides with a
    # concurrent writer or a stale temp from a previous crash.
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")

    # O_EXCL: fail if the temp already exists (never follow/overwrite it).
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        # O_CREAT mode is masked by umask; force 0o600 explicitly. fchmod is
        # POSIX-only; Windows has no equivalent permission model.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    # Atomic swap into place (same directory → same filesystem).
    try:
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def read_secure_json(path: Path, *, migrate: bool = True) -> Any:
    """Read a credential JSON file, transparently decrypting envelopes.

    Plaintext files are accepted for backward compatibility; when a key is
    available and ``migrate`` is True, the plaintext file is re-written
    encrypted in place (same path, 0o600) so the cleartext copy is replaced.

    Raises:
        CredentialStoreError: encrypted file but keyring unavailable, or
            decryption failed.
        json.JSONDecodeError / OSError: propagated from the underlying read.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    if not is_encrypted(data):
        if migrate:
            key = get_encryption_key()
            if key is not None:
                try:
                    write_secure_json(path, data)
                    logger.info(f"Migrated plaintext credential file to encrypted storage: {path}")
                except OSError as e:
                    logger.debug(f"Could not migrate {path} to encrypted storage: {e}")
        return data

    key = get_encryption_key()
    if key is None:
        raise CredentialStoreError(
            f"Credential file {path} is encrypted but the system keyring is "
            "unavailable (no Secret Service/DBus session?). Run from a desktop "
            "session, or re-authenticate with 'nlm login' after setting "
            f"{DISABLE_ENCRYPTION_ENV}=1 to use plaintext storage."
        )
    return decrypt_payload(data, key)
