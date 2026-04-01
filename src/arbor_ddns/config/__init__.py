"""Outside-workspace config and scaffold resource helpers."""

from arbor_ddns.config.merge import deep_merge
from arbor_ddns.config.outside_workspace import (
    OUTSIDE_WORKSPACE_RESOURCE_SPEC,
    OutsideWorkspaceConfig,
)
from arbor_ddns.config.resources import read_json, read_json_mapping, read_text
from arbor_ddns.config.scaffold import (
    SCAFFOLD_ENTRIES_RESOURCE_SPEC,
    SCAFFOLD_LAYOUT_RESOURCE_SPEC,
    SCAFFOLD_SECRETS_README_RESOURCE_SPEC,
    SCAFFOLD_WORKSPACE_RESOURCE_SPEC,
    ScaffoldLayout,
    load_entries_scaffold_defaults,
    load_scaffold_layout,
    load_scaffold_secrets_readme,
    load_workspace_scaffold_defaults,
)
from arbor_ddns.config.shared import DiscoveryCommandPaths

__all__ = [
    "DiscoveryCommandPaths",
    "OUTSIDE_WORKSPACE_RESOURCE_SPEC",
    "OutsideWorkspaceConfig",
    "SCAFFOLD_ENTRIES_RESOURCE_SPEC",
    "SCAFFOLD_LAYOUT_RESOURCE_SPEC",
    "SCAFFOLD_SECRETS_README_RESOURCE_SPEC",
    "SCAFFOLD_WORKSPACE_RESOURCE_SPEC",
    "ScaffoldLayout",
    "deep_merge",
    "load_entries_scaffold_defaults",
    "load_scaffold_layout",
    "load_scaffold_secrets_readme",
    "load_workspace_scaffold_defaults",
    "read_json",
    "read_json_mapping",
    "read_text",
]
