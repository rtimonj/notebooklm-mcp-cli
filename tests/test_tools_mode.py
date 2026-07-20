"""Tests for the NLM_TOOLS_MODE security tiers and per-mode registration."""

from unittest.mock import MagicMock

import pytest

from notebooklm_tools.mcp import tool_groups
from notebooklm_tools.mcp.tools import _utils


def _registered_tool_names() -> set[str]:
    """The full set of tool names collected by the @logged_tool registry.

    Importing the tools package (done at server import) is what populates the
    registry; the MCP server module is imported by the test session already.
    """
    import notebooklm_tools.mcp.server  # noqa: F401  (ensures modules imported)

    return {name for name, _ in _utils._tool_registry}


# ---------------------------------------------------------------------------
# Tier integrity
# ---------------------------------------------------------------------------


def test_tiers_are_disjoint():
    seen: dict[str, str] = {}
    tiers = {
        "READ": tool_groups.TIER_READ,
        "WRITE": tool_groups.TIER_WRITE,
        "DANGEROUS": tool_groups.TIER_DANGEROUS,
    }
    for tier, names in tiers.items():
        for name in names:
            assert name not in seen, f"{name} in both {seen.get(name)} and {tier}"
            seen[name] = tier


def test_all_tools_is_union_of_tiers():
    assert tool_groups.ALL_TOOLS == (
        tool_groups.TIER_READ | tool_groups.TIER_WRITE | tool_groups.TIER_DANGEROUS
    )


def test_tiers_cover_exactly_the_registered_tools():
    """The tier map must track the real registry with no drift in either direction."""
    registered = _registered_tool_names()
    assert registered == tool_groups.ALL_TOOLS, {
        "missing_from_tiers": registered - tool_groups.ALL_TOOLS,
        "stale_in_tiers": tool_groups.ALL_TOOLS - registered,
    }


def test_expected_tier_sizes():
    assert len(tool_groups.TIER_READ) == 15
    assert len(tool_groups.TIER_WRITE) == 17
    assert len(tool_groups.TIER_DANGEROUS) == 7


# ---------------------------------------------------------------------------
# tools_for_mode / mode_exclusions
# ---------------------------------------------------------------------------


def test_readonly_mode_exposes_only_read_tier():
    assert tool_groups.tools_for_mode("readonly") == tool_groups.TIER_READ


def test_standard_mode_exposes_read_and_write():
    assert tool_groups.tools_for_mode("standard") == (
        tool_groups.TIER_READ | tool_groups.TIER_WRITE
    )


def test_full_mode_exposes_everything():
    assert tool_groups.tools_for_mode("full") == tool_groups.ALL_TOOLS


def test_dangerous_tools_absent_from_standard():
    standard = tool_groups.tools_for_mode("standard")
    for name in ("notebook_share_public", "notebook_delete", "source_delete", "batch"):
        assert name not in standard


def test_write_tools_absent_from_readonly():
    readonly = tool_groups.tools_for_mode("readonly")
    for name in ("notebook_create", "source_add", "studio_create"):
        assert name not in readonly


def test_mode_exclusions_complements_tools_for_mode():
    for mode in ("readonly", "standard", "full"):
        exposed = tool_groups.tools_for_mode(mode)
        excluded = tool_groups.mode_exclusions(mode)
        assert exposed | excluded == tool_groups.ALL_TOOLS
        assert exposed & excluded == set()


def test_invalid_mode_raises_valueerror():
    with pytest.raises(ValueError, match="Invalid tools mode"):
        tool_groups.tools_for_mode("nonsense")
    with pytest.raises(ValueError, match="Invalid tools mode"):
        tool_groups.mode_exclusions("nonsense")


# ---------------------------------------------------------------------------
# resolve_mode: env override precedence
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_config(monkeypatch):
    from notebooklm_tools.utils import config

    monkeypatch.delenv("NLM_TOOLS_MODE", raising=False)
    config.reset_config()
    yield
    config.reset_config()


def test_resolve_mode_default_is_standard(clean_config):
    assert tool_groups.resolve_mode() == "standard"


def test_resolve_mode_env_override(monkeypatch, clean_config):
    from notebooklm_tools.utils import config

    monkeypatch.setenv("NLM_TOOLS_MODE", "readonly")
    config.reset_config()
    assert tool_groups.resolve_mode() == "readonly"


def test_env_overrides_config_file(tmp_path, monkeypatch):
    from notebooklm_tools.utils import config

    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    config_file = tmp_path / "storage" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('[tools]\nmode = "full"\n')

    # Config file alone → full
    config.reset_config()
    monkeypatch.delenv("NLM_TOOLS_MODE", raising=False)
    assert tool_groups.resolve_mode() == "full"

    # Env var wins over config file
    monkeypatch.setenv("NLM_TOOLS_MODE", "readonly")
    config.reset_config()
    assert tool_groups.resolve_mode() == "readonly"
    config.reset_config()


# ---------------------------------------------------------------------------
# register_all_tools with exclusions
# ---------------------------------------------------------------------------


def test_register_all_tools_registers_everything_by_default():
    mcp = MagicMock()
    registered = _utils.register_all_tools(mcp)
    assert set(registered) == _registered_tool_names()
    assert mcp.tool.call_count == len(registered)


def test_register_all_tools_skips_excluded():
    mcp = MagicMock()
    exclude = tool_groups.TIER_DANGEROUS
    registered = _utils.register_all_tools(mcp, exclude=exclude)
    assert set(registered).isdisjoint(exclude)
    assert set(registered) == _registered_tool_names() - exclude
    assert mcp.tool.call_count == len(registered)


@pytest.mark.parametrize(
    "mode,expected_count",
    [("readonly", 15), ("standard", 32), ("full", 39)],
)
def test_registration_count_per_mode(mode, expected_count):
    mcp = MagicMock()
    exclude = tool_groups.mode_exclusions(mode)
    registered = _utils.register_all_tools(mcp, exclude=exclude)
    assert len(registered) == expected_count
    assert set(registered) == tool_groups.tools_for_mode(mode)


# ---------------------------------------------------------------------------
# Env-var gating cannot resurrect a mode-excluded tool
# ---------------------------------------------------------------------------


def test_deletion_allowed_only_in_full():
    assert tool_groups.deletion_allowed("full") is True
    assert tool_groups.deletion_allowed("standard") is False
    assert tool_groups.deletion_allowed("readonly") is False


@pytest.mark.parametrize("mode", ["readonly", "standard"])
def test_note_delete_blocked_outside_full(monkeypatch, mode):
    from notebooklm_tools.mcp.tools import notes

    monkeypatch.setattr(tool_groups, "resolve_mode", lambda: mode)
    # get_client must never be reached for a blocked delete.
    monkeypatch.setattr(
        notes, "get_client", lambda: (_ for _ in ()).throw(AssertionError("client built"))
    )

    result = notes.note(notebook_id="nb", action="delete", note_id="n1", confirm=True)
    assert result["status"] == "error"
    assert "deletion is disabled" in result["error"]
    assert "NLM_TOOLS_MODE=full" in result["hint"]


@pytest.mark.parametrize("mode", ["readonly", "standard"])
def test_label_delete_blocked_outside_full(monkeypatch, mode):
    from notebooklm_tools.mcp.tools import labels

    monkeypatch.setattr(tool_groups, "resolve_mode", lambda: mode)
    monkeypatch.setattr(
        labels, "get_client", lambda: (_ for _ in ()).throw(AssertionError("client built"))
    )

    result = labels.label(notebook_id="nb", action="delete", label_id="l1", confirm=True)
    assert result["status"] == "error"
    assert "deletion is disabled" in result["error"]


def test_note_delete_reaches_service_in_full(monkeypatch):
    """In full mode the guard is transparent; delete proceeds to the service."""
    from notebooklm_tools.mcp.tools import notes

    monkeypatch.setattr(tool_groups, "resolve_mode", lambda: "full")
    monkeypatch.setattr(notes, "get_client", lambda: object())
    called = {}

    def fake_delete(client, nb, nid):
        called["args"] = (nb, nid)
        return {"deleted": nid}

    monkeypatch.setattr(notes.notes_service, "delete_note", fake_delete)

    result = notes.note(notebook_id="nb", action="delete", note_id="n1", confirm=True)
    assert result["status"] == "success"
    assert called["args"] == ("nb", "n1")


def test_note_create_still_works_in_standard(monkeypatch):
    """Non-destructive note actions remain available in standard mode."""
    from notebooklm_tools.mcp.tools import notes

    monkeypatch.setattr(tool_groups, "resolve_mode", lambda: "standard")
    monkeypatch.setattr(notes, "get_client", lambda: object())
    monkeypatch.setattr(
        notes.notes_service,
        "create_note",
        lambda client, nb, content, title: {"id": "new"},
    )

    result = notes.note(notebook_id="nb", action="create", content="hi")
    assert result["status"] == "success"


def test_mode_exclusion_is_registration_level_not_env_gating():
    """A tool excluded by mode is never registered, regardless of env gating.

    NOTEBOOKLM_ENABLED_TOOLS only re-enables *registered* tools via the
    visibility transform; it cannot bring back one the mode never registered.
    """
    mcp = MagicMock()
    exclude = tool_groups.mode_exclusions("readonly")
    registered = _utils.register_all_tools(mcp, exclude=exclude)
    assert "notebook_delete" not in registered
    assert "source_add" not in registered


# ---------------------------------------------------------------------------
# ToolsConfig persistence
# ---------------------------------------------------------------------------


def test_tools_config_default_is_standard():
    from notebooklm_tools.utils.config import Config

    assert Config().tools.mode == "standard"


def test_config_toml_roundtrips_tools_mode(tmp_path, monkeypatch):
    from notebooklm_tools.utils import config

    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    monkeypatch.delenv("NLM_TOOLS_MODE", raising=False)

    cfg = config.Config(tools=config.ToolsConfig(mode="readonly"))
    config.save_config(cfg)

    assert "[tools]" in config.get_config_file().read_text()

    config.reset_config()
    assert config.load_config().tools.mode == "readonly"
    config.reset_config()
