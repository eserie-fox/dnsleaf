"""Workspace scaffold resource loaders."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from dnsleaf.config.resources import read_json_mapping, read_text

WORKSPACE_RESOURCE_SPEC = "pkg://dnsleaf/config_defaults/workspace.json"
ENTRIES_RESOURCE_SPEC = "pkg://dnsleaf/config_defaults/entries.json"
SCAFFOLD_LAYOUT_RESOURCE_SPEC = "pkg://dnsleaf/templates/layout.json"
SCAFFOLD_SECRETS_README_RESOURCE_SPEC = "pkg://dnsleaf/templates/secrets_readme.txt"


class ScaffoldLayout(BaseModel):
    """Directory layout definition for scaffolded workspaces."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    directories: list[str]

    @field_validator("directories")
    @classmethod
    def _validate_directories(cls, values: list[str]) -> list[str]:
        for value in values:
            stripped = value.strip()
            if not stripped or stripped.startswith("/") or stripped in {".", ".."}:
                raise ValueError(f"invalid scaffold directory entry: {value!r}")
        return values


def load_workspace_defaults() -> dict[str, Any]:
    """Load package-shipped starter content for ``workspace.yaml``."""

    return read_json_mapping(WORKSPACE_RESOURCE_SPEC)


def load_entries_defaults() -> dict[str, Any]:
    """Load package-shipped starter content for ``entries.yaml``."""

    return read_json_mapping(ENTRIES_RESOURCE_SPEC)


def load_scaffold_layout() -> ScaffoldLayout:
    """Load the scaffold directory layout definition."""

    return ScaffoldLayout.model_validate(read_json_mapping(SCAFFOLD_LAYOUT_RESOURCE_SPEC))


def load_scaffold_secrets_readme() -> str:
    """Load the scaffold ``secrets/README.txt`` content."""

    return read_text(SCAFFOLD_SECRETS_README_RESOURCE_SPEC)


__all__ = [
    "ENTRIES_RESOURCE_SPEC",
    "SCAFFOLD_LAYOUT_RESOURCE_SPEC",
    "SCAFFOLD_SECRETS_README_RESOURCE_SPEC",
    "WORKSPACE_RESOURCE_SPEC",
    "ScaffoldLayout",
    "load_entries_defaults",
    "load_scaffold_layout",
    "load_scaffold_secrets_readme",
    "load_workspace_defaults",
]
