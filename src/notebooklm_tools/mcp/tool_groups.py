"""Optional group-based gating of MCP tools.

The server registers a large tool set (39 tools). Clients that only need a
subset can hide the rest to save context, without editing code, by toggling
named groups or individual tools through environment variables.

Gating is opt-in: with no configuration, every tool stays visible and behavior
is unchanged.

Resolution order (later wins for a given tool):
  1. env NOTEBOOKLM_DISABLED_GROUPS (comma-separated group names) hides whole
     groups.
  2. env NOTEBOOKLM_DISABLED_TOOLS (comma-separated tool names) hides single
     tools.
  3. env NOTEBOOKLM_ENABLED_TOOLS (comma-separated tool names) re-enables single
     tools, overriding the two above.

apply(mcp) is called once from server._register_tools() after all tools are
registered. It uses FastMCP's visibility transform
(mcp.local_provider.disable(names=...)) so no tool is unregistered, only hidden.
"""

from __future__ import annotations

import os
from typing import Any

# Read/manage split so a query-first client can hide mutating tools while
# keeping the read + chat core. Each tool name appears in exactly one group;
# together the groups cover every registered tool.
TOOL_GROUPS: dict[str, set[str]] = {
    "notebooks_read": {
        "notebook_list",
        "notebook_get",
        "notebook_describe",
    },
    "notebooks_manage": {
        "notebook_create",
        "notebook_rename",
        "notebook_delete",
    },
    "sources_read": {
        "source_list_drive",
        "source_describe",
        "source_get_content",
    },
    "sources_manage": {
        "source_add",
        "source_rename",
        "source_delete",
        "source_sync_drive",
    },
    "chat": {
        "notebook_query",
        "chat_configure",
        "notebook_query_start",
        "notebook_query_status",
    },
    "query_multi": {
        "cross_notebook_query",
    },
    "organization": {
        "label",
        "tag",
    },
    "automation": {
        "batch",
        "pipeline",
    },
    "notes": {
        "note",
    },
    "auth": {
        "refresh_auth",
        "save_auth_tokens",
    },
    "server": {
        "server_info",
    },
    "sharing": {
        "notebook_share_status",
        "notebook_share_public",
        "notebook_share_invite",
        "notebook_share_batch",
    },
    "research": {
        "research_start",
        "research_status",
        "research_import",
    },
    "studio": {
        "studio_create",
        "studio_status",
        "studio_delete",
        "studio_revise",
        "download_artifact",
        "export_artifact",
    },
}


# ---------------------------------------------------------------------------
# Security tiers (used by the NLM_TOOLS_MODE / [tools].mode gate)
# ---------------------------------------------------------------------------
#
# Every registered tool belongs to exactly one tier. Modes are cumulative:
#   readonly → READ
#   standard → READ + WRITE
#   full     → READ + WRITE + DANGEROUS
#
# Excluded tools are NOT registered with the MCP server (they never appear in
# tools/list), so a smaller mode both saves context and removes the temptation
# for an agent to call a tool it shouldn't. This is stronger than the env-var
# gating below, which only hides already-registered tools.

# Read-only: listing, querying, describing, status, local downloads.
TIER_READ: set[str] = {
    "notebook_list",
    "notebook_get",
    "notebook_describe",
    "source_list_drive",
    "source_describe",
    "source_get_content",
    "notebook_query",
    "notebook_query_start",
    "notebook_query_status",
    "cross_notebook_query",
    "notebook_share_status",
    "studio_status",
    "download_artifact",
    "server_info",
    "refresh_auth",
}

# Normal writes: create/rename, add sources, generate artifacts, notes/labels.
# Excludes public sharing, collaborator invites, and deletions.
TIER_WRITE: set[str] = {
    "notebook_create",
    "notebook_rename",
    "source_add",
    "source_rename",
    "source_sync_drive",
    "chat_configure",
    "research_start",
    "research_status",  # auto_import=True can import sources → not read-only
    "research_import",
    "studio_create",
    "studio_revise",
    "export_artifact",
    "note",
    "label",
    "tag",
    "pipeline",
    "save_auth_tokens",
}

# Dangerous: public exposure, mass invites, irreversible deletion.
# `batch` lives here because action=delete removes notebooks irreversibly.
TIER_DANGEROUS: set[str] = {
    "notebook_share_public",
    "notebook_share_invite",
    "notebook_share_batch",
    "notebook_delete",
    "source_delete",
    "studio_delete",
    "batch",
}

# Tools available in each mode (cumulative).
MODE_READONLY = "readonly"
MODE_STANDARD = "standard"
MODE_FULL = "full"
VALID_MODES = (MODE_READONLY, MODE_STANDARD, MODE_FULL)

_MODE_TOOLS: dict[str, set[str]] = {
    MODE_READONLY: TIER_READ,
    MODE_STANDARD: TIER_READ | TIER_WRITE,
    MODE_FULL: TIER_READ | TIER_WRITE | TIER_DANGEROUS,
}

ALL_TOOLS: set[str] = TIER_READ | TIER_WRITE | TIER_DANGEROUS


def tools_for_mode(mode: str) -> set[str]:
    """Return the set of tool names exposed in the given mode.

    Raises:
        ValueError: if the mode is not one of readonly/standard/full.
    """
    try:
        return _MODE_TOOLS[mode]
    except KeyError as e:
        raise ValueError(
            f"Invalid tools mode {mode!r}. Valid values: {', '.join(VALID_MODES)}."
        ) from e


def mode_exclusions(mode: str) -> set[str]:
    """Return the tool names to exclude (not register) for the given mode."""
    return ALL_TOOLS - tools_for_mode(mode)


def resolve_mode() -> str:
    """Resolve the active tools mode from config (env override applied there)."""
    from notebooklm_tools.utils.config import get_config

    return get_config().tools.mode


def deletion_allowed(mode: str | None = None) -> bool:
    """Whether irreversible deletion sub-actions are permitted in *mode*.

    Some consolidated tools (``note``, ``label``) stay registered in the
    ``standard`` tier because their non-destructive actions (create, list,
    rename, …) are normal writes — but their ``delete`` sub-action is dangerous.
    Since gating happens per-tool at registration, those tools guard the delete
    path at call time with this helper. Deletion is only allowed in ``full``.
    """
    if mode is None:
        mode = resolve_mode()
    return mode == MODE_FULL


def _env_names(var: str) -> set[str]:
    raw = os.environ.get(var, "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _resolve_disabled() -> set[str]:
    """Compute the final set of tool names to hide (empty unless configured)."""
    names: set[str] = set()
    for group in _env_names("NOTEBOOKLM_DISABLED_GROUPS"):
        names |= TOOL_GROUPS.get(group, set())

    names |= _env_names("NOTEBOOKLM_DISABLED_TOOLS")
    names -= _env_names("NOTEBOOKLM_ENABLED_TOOLS")
    return names


def apply(mcp: Any) -> set[str]:
    """Hide the resolved set of tools on the given FastMCP instance.

    Returns the set of hidden tool names (empty if nothing was hidden).
    """
    names = _resolve_disabled()
    if names:
        mcp.local_provider.disable(names=names)
    return names
