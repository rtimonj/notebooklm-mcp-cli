"""Tests for encryption-at-rest of credential files (utils/credential_store)."""

import json
import logging
import os
import stat

import pytest
from cryptography.fernet import Fernet

from notebooklm_tools.utils import credential_store
from notebooklm_tools.utils.credential_store import (
    ENVELOPE_MARKER,
    CredentialStoreError,
    decrypt_payload,
    encrypt_payload,
    is_encrypted,
    read_secure_json,
    write_secure_json,
)


@pytest.fixture
def key():
    return Fernet.generate_key()


@pytest.fixture
def with_key(monkeypatch, key):
    """Simulate an available keyring with a fixed in-memory key."""
    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: key)
    return key


@pytest.fixture
def without_key(monkeypatch):
    """Simulate an unavailable keyring (not an explicit opt-out)."""
    monkeypatch.delenv(credential_store.DISABLE_ENCRYPTION_ENV, raising=False)
    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: None)


# ---------------------------------------------------------------------------
# Envelope primitives
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip_dict(key):
    payload = {"cookies": {"SID": "abc"}, "csrf_token": "tok"}
    envelope = encrypt_payload(payload, key)
    assert is_encrypted(envelope)
    assert "SID" not in json.dumps(envelope)
    assert decrypt_payload(envelope, key) == payload


def test_encrypt_decrypt_roundtrip_list(key):
    payload = [{"name": "SID", "value": "abc", "domain": ".google.com"}]
    envelope = encrypt_payload(payload, key)
    assert decrypt_payload(envelope, key) == payload


def test_is_encrypted_rejects_plaintext():
    assert not is_encrypted({"cookies": {}})
    assert not is_encrypted([{"name": "SID"}])
    assert not is_encrypted("string")
    assert not is_encrypted({ENVELOPE_MARKER: 2})


def test_decrypt_with_wrong_key_raises(key):
    envelope = encrypt_payload({"a": 1}, key)
    with pytest.raises(CredentialStoreError):
        decrypt_payload(envelope, Fernet.generate_key())


def test_decrypt_corrupted_ciphertext_raises(key):
    envelope = encrypt_payload({"a": 1}, key)
    envelope["ciphertext"] = envelope["ciphertext"][:-4] + "AAAA"
    with pytest.raises(CredentialStoreError):
        decrypt_payload(envelope, key)


# ---------------------------------------------------------------------------
# write_secure_json / read_secure_json
# ---------------------------------------------------------------------------


def test_write_encrypted_and_read_back(tmp_path, with_key):
    path = tmp_path / "cookies.json"
    payload = {"SID": "secret-value"}
    write_secure_json(path, payload)

    on_disk = json.loads(path.read_text())
    assert is_encrypted(on_disk)
    assert "secret-value" not in path.read_text()
    assert read_secure_json(path) == payload


def test_write_creates_file_with_0600_permissions(tmp_path, with_key):
    path = tmp_path / "cookies.json"
    write_secure_json(path, {"a": 1})
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_write_plaintext_fallback_warns_once(tmp_path, without_key, caplog):
    credential_store.reset_cache()
    path = tmp_path / "cookies.json"
    with caplog.at_level(logging.WARNING, logger="notebooklm_tools.utils.credential_store"):
        write_secure_json(path, {"a": 1})
        write_secure_json(path, {"a": 2})

    warnings = [r for r in caplog.records if "PLAINTEXT" in r.getMessage()]
    assert len(warnings) == 1
    assert json.loads(path.read_text()) == {"a": 2}


def test_write_is_atomic_no_temp_left_behind(tmp_path, with_key):
    path = tmp_path / "cookies.json"
    write_secure_json(path, {"a": 1})
    # No leftover temp files in the directory.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "cookies.json"]
    assert leftovers == []
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_write_overwrite_preserves_permissions_and_content(tmp_path, with_key):
    path = tmp_path / "cookies.json"
    write_secure_json(path, {"a": 1})
    write_secure_json(path, {"a": 2})  # overwrite via atomic replace
    assert read_secure_json(path) == {"a": 2}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["cookies.json"]


def test_write_failure_does_not_clobber_existing_file(tmp_path, with_key, monkeypatch):
    """If serialization fails, the pre-existing file must stay intact."""
    path = tmp_path / "cookies.json"
    write_secure_json(path, {"good": 1})

    # Make json.dump blow up mid-write.
    def boom(*a, **k):
        raise ValueError("kaboom")

    monkeypatch.setattr(credential_store.json, "dump", boom)
    with pytest.raises(ValueError):
        write_secure_json(path, {"bad": 2})

    # Original content preserved, no temp file left.
    assert read_secure_json(path) == {"good": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["cookies.json"]


def test_write_fails_closed_when_encryption_required(tmp_path, without_key, monkeypatch):
    monkeypatch.setattr(credential_store, "_require_encryption", lambda: True)
    path = tmp_path / "cookies.json"
    with pytest.raises(CredentialStoreError, match="Encryption is required"):
        write_secure_json(path, {"SID": "x"})
    assert not path.exists()  # nothing written


def test_write_degrades_with_warning_when_not_required(tmp_path, without_key, monkeypatch, caplog):
    monkeypatch.setattr(credential_store, "_require_encryption", lambda: False)
    credential_store.reset_cache()
    path = tmp_path / "cookies.json"
    with caplog.at_level(logging.WARNING, logger="notebooklm_tools.utils.credential_store"):
        write_secure_json(path, {"SID": "x"})
    assert path.exists()
    assert not is_encrypted(json.loads(path.read_text()))
    assert any("PLAINTEXT" in r.getMessage() for r in caplog.records)


def test_require_encryption_env_wiring(tmp_path, monkeypatch):
    """NLM_REQUIRE_ENCRYPTION flows through config into _require_encryption()."""
    from notebooklm_tools.utils import config as cfg

    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("NLM_REQUIRE_ENCRYPTION", "1")
    cfg.reset_config()
    assert credential_store._require_encryption() is True

    monkeypatch.setenv("NLM_REQUIRE_ENCRYPTION", "0")
    cfg.reset_config()
    assert credential_store._require_encryption() is False
    cfg.reset_config()


def test_plaintext_fallback_active(monkeypatch):
    monkeypatch.delenv(credential_store.DISABLE_ENCRYPTION_ENV, raising=False)
    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: None)
    assert credential_store.plaintext_fallback_active() is True

    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: b"key")
    assert credential_store.plaintext_fallback_active() is False

    # Explicit opt-out is not an unexpected downgrade → no warning.
    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: None)
    monkeypatch.setenv(credential_store.DISABLE_ENCRYPTION_ENV, "1")
    assert credential_store.plaintext_fallback_active() is False


def test_read_plaintext_without_key_returns_data(tmp_path, without_key):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps({"SID": "abc"}))
    assert read_secure_json(path) == {"SID": "abc"}
    # No key: file must stay plaintext
    assert not is_encrypted(json.loads(path.read_text()))


def test_read_migrates_plaintext_to_encrypted(tmp_path, with_key):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps({"SID": "abc"}))

    assert read_secure_json(path) == {"SID": "abc"}

    on_disk = json.loads(path.read_text())
    assert is_encrypted(on_disk)
    assert "abc" not in path.read_text()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # And reads back fine after migration
    assert read_secure_json(path) == {"SID": "abc"}


def test_read_migrate_false_leaves_plaintext(tmp_path, with_key):
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps({"SID": "abc"}))
    assert read_secure_json(path, migrate=False) == {"SID": "abc"}
    assert not is_encrypted(json.loads(path.read_text()))


def test_read_encrypted_without_key_raises(tmp_path, key, monkeypatch):
    path = tmp_path / "cookies.json"
    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: key)
    write_secure_json(path, {"SID": "abc"})

    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: None)
    with pytest.raises(CredentialStoreError, match="keyring"):
        read_secure_json(path)


# ---------------------------------------------------------------------------
# Keyring key management
# ---------------------------------------------------------------------------


def test_get_encryption_key_disabled_by_env(monkeypatch):
    monkeypatch.setenv(credential_store.DISABLE_ENCRYPTION_ENV, "1")
    credential_store.reset_cache()
    assert credential_store.get_encryption_key() is None


def test_get_encryption_key_creates_and_reuses(monkeypatch):
    monkeypatch.delenv(credential_store.DISABLE_ENCRYPTION_ENV, raising=False)
    credential_store.reset_cache()

    store: dict[tuple[str, str], str] = {}

    class FakeKeyring:
        @staticmethod
        def get_password(service, name):
            return store.get((service, name))

        @staticmethod
        def set_password(service, name, value):
            store[(service, name)] = value

    monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)

    key1 = credential_store.get_encryption_key()
    assert key1 is not None
    assert store  # key was persisted

    credential_store.reset_cache()
    key2 = credential_store.get_encryption_key()
    assert key2 == key1  # reused, not regenerated


def test_get_encryption_key_concurrent_access_generates_one_key(monkeypatch):
    """Two threads hitting first-use together must produce a single shared key."""
    import threading
    import time

    monkeypatch.delenv(credential_store.DISABLE_ENCRYPTION_ENV, raising=False)
    credential_store.reset_cache()

    store: dict[tuple[str, str], str] = {}
    set_calls = 0
    counter_lock = threading.Lock()

    class SlowKeyring:
        @staticmethod
        def get_password(service, name):
            time.sleep(0.02)  # widen the race window
            return store.get((service, name))

        @staticmethod
        def set_password(service, name, value):
            nonlocal set_calls
            with counter_lock:
                set_calls += 1
            store[(service, name)] = value

    monkeypatch.setitem(__import__("sys").modules, "keyring", SlowKeyring)

    results: list[bytes | None] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()  # start both threads as simultaneously as possible
        key = credential_store.get_encryption_key()
        with results_lock:
            results.append(key)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert set_calls == 1, "key must be generated/stored exactly once"
    assert results[0] is not None
    assert results[0] == results[1], "both threads must observe the same key"


def test_get_encryption_key_keyring_unavailable(monkeypatch):
    monkeypatch.delenv(credential_store.DISABLE_ENCRYPTION_ENV, raising=False)
    credential_store.reset_cache()

    class BrokenKeyring:
        @staticmethod
        def get_password(service, name):
            raise RuntimeError("no dbus")

    monkeypatch.setitem(__import__("sys").modules, "keyring", BrokenKeyring)
    assert credential_store.get_encryption_key() is None


# ---------------------------------------------------------------------------
# AuthManager integration
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    from notebooklm_tools.core.auth import AuthManager

    return AuthManager("default")


COOKIES = {"SID": "s", "HSID": "h", "SSID": "ss", "APISID": "a", "SAPISID": "sa"}


def test_auth_manager_save_load_encrypted(manager, with_key):
    manager.save_profile(cookies=COOKIES, csrf_token="csrf", email="a@b.com")

    raw_cookies = json.loads(manager.cookies_file.read_text())
    raw_metadata = json.loads(manager.metadata_file.read_text())
    assert is_encrypted(raw_cookies)
    assert is_encrypted(raw_metadata)
    assert "csrf" not in manager.metadata_file.read_text()

    profile = manager.load_profile(force_reload=True)
    assert profile.cookies == COOKIES
    assert profile.csrf_token == "csrf"
    assert profile.email == "a@b.com"


def test_auth_manager_migrates_plaintext_profile(manager, with_key):
    # Simulate a pre-encryption profile written in plaintext
    manager.profile_dir.mkdir(parents=True, exist_ok=True)
    manager.cookies_file.write_text(json.dumps(COOKIES))
    manager.metadata_file.write_text(json.dumps({"csrf_token": "old", "email": "a@b.com"}))

    profile = manager.load_profile()
    assert profile.cookies == COOKIES
    assert profile.csrf_token == "old"

    assert is_encrypted(json.loads(manager.cookies_file.read_text()))
    assert is_encrypted(json.loads(manager.metadata_file.read_text()))


def test_auth_manager_plaintext_still_works_without_keyring(manager, without_key):
    manager.save_profile(cookies=COOKIES, csrf_token="csrf")
    assert not is_encrypted(json.loads(manager.cookies_file.read_text()))
    profile = manager.load_profile(force_reload=True)
    assert profile.cookies == COOKIES


def test_auth_manager_account_mismatch_guard_with_encryption(manager, with_key):
    from notebooklm_tools.core.exceptions import AccountMismatchError

    manager.save_profile(cookies=COOKIES, email="first@x.com")
    with pytest.raises(AccountMismatchError):
        manager.save_profile(cookies=COOKIES, email="second@x.com")


def test_auth_manager_encrypted_profile_without_keyring_raises(manager, key, monkeypatch):
    from notebooklm_tools.core.exceptions import AuthenticationError

    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: key)
    manager.save_profile(cookies=COOKIES)

    monkeypatch.setattr(credential_store, "get_encryption_key", lambda: None)
    with pytest.raises(AuthenticationError, match="keyring"):
        manager.load_profile(force_reload=True)


# ---------------------------------------------------------------------------
# Legacy auth.json cache integration
# ---------------------------------------------------------------------------


def test_save_and_load_cached_tokens_encrypted(tmp_path, monkeypatch, with_key):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    from notebooklm_tools.core.auth import (
        AuthTokens,
        get_cache_path,
        load_cached_tokens,
        save_tokens_to_cache,
    )

    tokens = AuthTokens(cookies=COOKIES, csrf_token="csrf", extracted_at=123.0)
    save_tokens_to_cache(tokens, silent=True)

    assert is_encrypted(json.loads(get_cache_path().read_text()))

    loaded = load_cached_tokens()
    assert loaded is not None
    assert loaded.cookies == COOKIES
    assert loaded.csrf_token == "csrf"


def test_load_cached_tokens_migrates_plaintext(tmp_path, monkeypatch, with_key):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    from notebooklm_tools.core.auth import get_cache_path, load_cached_tokens

    cache = get_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"cookies": COOKIES, "extracted_at": 123.0}))

    loaded = load_cached_tokens()
    assert loaded is not None
    assert loaded.cookies == COOKIES
    assert is_encrypted(json.loads(cache.read_text()))


def test_active_auth_mtime_tracks_encrypted_writes(tmp_path, monkeypatch, with_key):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    from notebooklm_tools.core.auth import AuthManager
    from notebooklm_tools.services.auth import get_active_auth_mtime

    assert get_active_auth_mtime() == 0.0
    AuthManager("default").save_profile(cookies=COOKIES)
    assert get_active_auth_mtime() > 0.0
