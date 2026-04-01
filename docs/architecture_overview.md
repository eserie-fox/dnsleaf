# Architecture Overview

## Core flow

The runtime flow is:

`workspace source -> discovery -> selection -> planner -> apply/state`

More explicitly:

1. `workspace.yaml` and `entries.yaml` are loaded from a workspace directory.
2. Dynamic entries use discovery backends to gather IPv4 and IPv6 candidates from PVE guests or the local host.
3. The selector chooses one family-specific address or returns an explicit non-selection result.
4. Static entries bypass discovery and selection entirely.
5. Cloudflare current state is queried.
6. The planner decides `create`, `update`, `delete`, or `noop`.
7. Optional apply mutates Cloudflare state and updates workspace state files.

## Module boundaries

- `arbor_ddns.workspace`
  - loads and validates workspace source files
  - manages entry CRUD
  - renders derived artifacts
  - aggregates status and doctor output
- `arbor_ddns.discovery`
  - collects IPv4 and IPv6 candidate addresses from dynamic targets
  - contains family-specific selection logic
  - never calls DNS APIs
- `arbor_ddns.dns`
  - contains the Cloudflare provider and the generic planner
  - never decides which guest IP is better
- `arbor_ddns.sync`
  - performs thin orchestration for `plan` and `sync-once`
  - expands one entry into one or two concrete record flows
- `arbor_ddns.systemd`
  - renders unit files
  - installs, uninstalls, and queries systemd units
- `arbor_ddns.config`
  - outside-workspace defaults
  - package-resource scaffold defaults and loaders
  - canonical deep-merge behavior for outside-workspace/scaffold mappings
  - not an operator-facing config surface
- `arbor_ddns.logging`
  - configures simple root logging for non-workspace commands
  - applies workspace-scoped logging contexts at command boundaries
  - keeps a stable symlink plus daily log files for workspace logs
  - resolves from `workspace.yaml` when a workspace is active

## Workspace as the source of truth

The primary editing surface is the workspace directory:

- `workspace.yaml`: zone-level and instance-level settings
- `entries.yaml`: managed entry list
- `rendered/`: generated artifacts
- `runtime/`: workspace-local logs and runtime files
- `state/`: apply and managed-record tracking

The older inventory-style model is no longer part of the workspace workflow.

Execution ownership is also workspace-centric:

- discovery command paths come from `workspace.yaml -> paths`
- systemd command and unit-directory paths come from `workspace.yaml -> paths`
- workspace logging comes from `workspace.yaml -> arbor_ddns_logging`

The only notable non-workspace exception is low-level `discover`, which can use internal fallback defaults when run outside a workspace.
Those fallback values come from the outside-workspace config, not from a second operator-facing runtime config.

## Cloudflare-only scope

The current implementation supports Cloudflare only. Provider abstractions remain clean, but user-facing docs and commands intentionally describe only the Cloudflare path.

## Future expansion

The workspace and entry services are designed so that future MCP or other machine-oriented integrations can call them directly without scraping CLI text output.
