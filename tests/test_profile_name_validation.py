"""Profile names must not enable path traversal (audit finding #6)."""

import pytest

from notebooklm_tools.utils.config import get_profile_dir, validate_profile_name

_BAD_NAMES = [
    "../../foo",
    "..",
    ".",
    "a/b",
    "a\\b",
    "foo/../bar",
    "/abs",
    "",
    "name with space",
    "emoji😀",
]

_GOOD_NAMES = ["default", "work", "personal-2", "a.b_c-1", "Team.Prod"]


@pytest.mark.parametrize("name", _BAD_NAMES)
def test_validate_rejects_bad_names(name):
    with pytest.raises(ValueError, match="Invalid profile name"):
        validate_profile_name(name)


@pytest.mark.parametrize("name", _GOOD_NAMES)
def test_validate_accepts_good_names(name):
    assert validate_profile_name(name) == name


def test_get_profile_dir_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    with pytest.raises(ValueError, match="Invalid profile name"):
        get_profile_dir("../../etc")


def test_get_profile_dir_stays_within_profiles_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    d = get_profile_dir("work")
    profiles_root = (tmp_path / "storage" / "profiles").resolve()
    assert d.resolve().parent == profiles_root


def test_auth_manager_rejects_traversal_name(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    from notebooklm_tools.core.auth import AuthManager

    with pytest.raises(ValueError, match="Invalid profile name"):
        AuthManager("../../../tmp/evil")
