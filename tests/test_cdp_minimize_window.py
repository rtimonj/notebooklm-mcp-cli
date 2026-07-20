"""Tests for minimizing the CDP debugging-port exposure window.

Covers:
- ephemeral random port selection (find_available_port)
- closing a launched Chrome when extraction fails (no leaked port)
- NOT closing a reused/foreign Chrome
- login_timeout propagation
"""

import pytest

from notebooklm_tools.core.exceptions import AuthenticationError
from notebooklm_tools.utils import cdp

# ---------------------------------------------------------------------------
# Ephemeral random port
# ---------------------------------------------------------------------------


def test_random_ephemeral_start_within_range():
    for _ in range(200):
        p = cdp._random_ephemeral_start(max_attempts=10)
        assert cdp._EPHEMERAL_PORT_MIN <= p <= cdp._EPHEMERAL_PORT_MAX - 10


def test_find_available_port_defaults_to_random_ephemeral(monkeypatch):
    calls = {}

    def fake_random_start(max_attempts=10):
        calls["max_attempts"] = max_attempts
        return 55000

    monkeypatch.setattr(cdp, "_random_ephemeral_start", fake_random_start)

    # Make the first bind succeed.
    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def bind(self, addr):
            assert addr == ("127.0.0.1", 55000)

    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())

    port = cdp.find_available_port()
    assert port == 55000
    assert calls["max_attempts"] == 10


def test_find_available_port_explicit_start_is_respected(monkeypatch):
    """Passing an explicit start bypasses randomization (backward compatible)."""
    seen = []

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def bind(self, addr):
            seen.append(addr[1])
            if addr[1] < 9223:
                raise OSError("in use")

    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
    # Should not call the random helper when an explicit start is given.
    monkeypatch.setattr(
        cdp,
        "_random_ephemeral_start",
        lambda *a, **k: pytest.fail("random start should not be used"),
    )

    port = cdp.find_available_port(starting_from=9222)
    assert port == 9223
    assert seen == [9222, 9223]


# ---------------------------------------------------------------------------
# Close-on-failure for launched Chrome
# ---------------------------------------------------------------------------


@pytest.fixture
def launched_chrome_env(monkeypatch, tmp_path):
    """Stub the launch path so extract_cookies_via_cdp 'launches' Chrome."""
    monkeypatch.setattr(cdp, "_kill_stale_nlm_browsers", lambda: None)
    monkeypatch.setattr(cdp, "find_existing_nlm_chrome", lambda **k: (None, None))
    monkeypatch.setattr(cdp, "get_chrome_path", lambda: "/usr/bin/google-chrome")
    monkeypatch.setattr(cdp, "_get_profile_dir_for_launch", lambda *a, **k: tmp_path)
    monkeypatch.setattr(cdp, "is_profile_locked", lambda *a, **k: False)
    monkeypatch.setattr(cdp, "find_available_port", lambda *a, **k: 55001)
    monkeypatch.setattr(cdp, "launch_chrome", lambda *a, **k: True)
    monkeypatch.setattr(cdp, "get_debugger_url", lambda *a, **k: "ws://127.0.0.1:55001/x")

    terminated = []
    monkeypatch.setattr(
        cdp, "terminate_chrome", lambda process=None, port=None: terminated.append(port) or True
    )
    return terminated


def test_extraction_failure_closes_launched_chrome(monkeypatch, launched_chrome_env):
    def boom(*a, **k):
        raise AuthenticationError(message="Login timeout")

    monkeypatch.setattr(cdp, "extract_cookies_from_page", boom)

    with pytest.raises(AuthenticationError):
        cdp.extract_cookies_via_cdp(auto_launch=True, wait_for_login=True, profile_name="default")

    assert launched_chrome_env == [55001], "launched Chrome must be terminated on failure"


def test_extraction_success_does_not_terminate_in_function(monkeypatch, launched_chrome_env):
    monkeypatch.setattr(
        cdp,
        "extract_cookies_from_page",
        lambda *a, **k: {"cookies": [{"name": "SID"}], "csrf_token": "t"},
    )

    result = cdp.extract_cookies_via_cdp(auto_launch=True, profile_name="default")

    assert result["reused_existing"] is False
    # Success path leaves closing to the caller (CLI), not the extractor.
    assert launched_chrome_env == []


def test_reused_browser_is_not_terminated_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(cdp, "_kill_stale_nlm_browsers", lambda: None)
    # Reuse an existing profile-owned Chrome.
    monkeypatch.setattr(
        cdp, "find_existing_nlm_chrome", lambda **k: (9222, "ws://127.0.0.1:9222/x")
    )

    terminated = []
    monkeypatch.setattr(
        cdp, "terminate_chrome", lambda process=None, port=None: terminated.append(port) or True
    )

    def boom(*a, **k):
        raise AuthenticationError(message="Login timeout")

    monkeypatch.setattr(cdp, "extract_cookies_from_page", boom)

    with pytest.raises(AuthenticationError):
        cdp.extract_cookies_via_cdp(auto_launch=True, profile_name="default")

    assert terminated == [], "a reused browser we did not launch must not be closed"


# ---------------------------------------------------------------------------
# login_timeout propagation
# ---------------------------------------------------------------------------


def test_login_timeout_is_propagated(monkeypatch, launched_chrome_env):
    captured = {}

    def capture(cdp_http_url, wait_for_login, login_timeout):
        captured["login_timeout"] = login_timeout
        return {"cookies": [{"name": "SID"}]}

    monkeypatch.setattr(cdp, "extract_cookies_from_page", capture)

    cdp.extract_cookies_via_cdp(auto_launch=True, login_timeout=120, profile_name="default")

    assert captured["login_timeout"] == 120
