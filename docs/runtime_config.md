# Runtime Config

`arbor-ddns` has two configuration layers:

1. app runtime config
2. workspace source config

This document describes the app runtime config.

## App runtime config

The app runtime config exists for program defaults such as:

- discovery command locations
- systemd installation defaults
- workspace scaffold defaults

It is not the main user editing surface for day-to-day management.

## Formal runtime config pattern

The app runtime config follows this fixed pattern:

1. read package defaults
2. read override mapping or JSON file
3. deep merge
4. validate with Pydantic v2

Public loaders:

- `AppConfig.from_defaults()`
- `AppConfig.from_file(path)`
- `AppConfig.from_mapping(data)`

## Package defaults

Defaults are shipped inside the package:

- `src/arbor_ddns/config_defaults/app.json`

This keeps install-time behavior deterministic and avoids host-specific assumptions.

## Deep merge rules

The merge helper is intentionally simple:

- mapping + mapping: recursive merge
- any other type pair: override replaces base completely
- lists are replaced, never concatenated

## Runtime-only resolution

Runtime resolution is not done during raw loading.

Examples:

- resolving the systemd unit directory path
- resolving workspace-relative token-file paths
- reading the Cloudflare token contents

Those steps happen explicitly at runtime, after the raw config object has already been validated.

## Relationship to workspace config

Workspace config lives in YAML inside the workspace directory and is the normal operator-facing surface.

See [Workspace](workspace.md) for the user-facing config model.
