# Runtime Config

`arbor-ddns` is workspace-centric.

For operators, the execution config lives in `workspace.yaml`. There is no CLI-level `--config` override and no separate operator-facing app config file.

## What still exists under `arbor_ddns.config`

The `arbor_ddns.config` package still contains an internal outside-workspace config layer for:

- package-shipped scaffold resources
- package-shipped outside-workspace defaults for non-workspace behavior
- the canonical deep-merge helper
- package resource loading helpers

This internal layer is not the main day-to-day editing surface.

## Outside-workspace config shape

The outside-workspace model is `OutsideWorkspaceConfig` and follows the formal runtime config pattern:

1. read package defaults
2. optionally read an override mapping or JSON file
3. deep merge
4. validate with Pydantic v2

Python API:

- `OutsideWorkspaceConfig.from_defaults()`
- `OutsideWorkspaceConfig.from_file(path)`
- `OutsideWorkspaceConfig.from_mapping(data)`

These helpers are useful for tests and internal wiring. They are not exposed as normal CLI configuration.

This model does not use `config_version`, because it is not an operator-facing long-lived config contract.

## What the outside-workspace config covers

The outside-workspace config is intentionally small:

- fallback discovery command paths for `discover` when it runs outside a workspace
- simple root stderr logging for commands that do not have a workspace context yet
- scaffold resource loading

They do not own workspace execution behavior such as:

- Cloudflare zone or token paths
- workspace logging destinations
- workspace systemd install locations
- workspace discovery command choices

Those belong to `workspace.yaml`.

## Shared schema with workspace config

Outside-workspace config and workspace config intentionally share sub-structures where the semantics are the same.

- Logging uses the same `arbor_ddns_logging` schema on both sides.
- Shared discovery command paths use the same `paths` sub-structure for:
  - `pct_bin`
  - `qm_bin`
  - `shell_bin`

Workspace config extends that with workspace-only fields such as:

- `systemctl_bin`
- `systemd_unit_dir`

Those workspace-only systemd fields are not present in the outside-workspace config.

## Package resources

Defaults and scaffold resources ship inside the package:

- `src/arbor_ddns/config_defaults/outside_workspace.json`
- `src/arbor_ddns/config_defaults/scaffold_workspace.json`
- `src/arbor_ddns/config_defaults/scaffold_entries.json`
- `src/arbor_ddns/config_defaults/scaffold_layout.json`
- `src/arbor_ddns/config_defaults/scaffold_secrets_readme.txt`

This keeps scaffold and fallback behavior deterministic and distribution-friendly.

## Deep merge rules

The merge helper is intentionally simple:

- mapping + mapping: recursive merge
- any other type pair: override replaces base completely
- lists are replaced, never concatenated

## Runtime-only resolution

Runtime resolution is explicit and happens after raw validation.

Examples:

- resolving `workspace.yaml -> api_token_file`
- resolving `workspace.yaml -> paths.systemd_unit_dir`
- resolving `workspace.yaml -> arbor_ddns_logging.file_path`
- reading the Cloudflare token contents

See [Workspace](workspace.md) for the operator-facing configuration model.
