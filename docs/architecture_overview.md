# Architecture Overview

## Core flow

The runtime flow is:

`workspace source -> discovery -> selection -> planner -> apply/state`

More explicitly:

1. `workspace.yaml` and `entries.yaml` are loaded from a workspace directory.
2. Discovery backends gather IPv6 candidates from PVE.
3. The selector chooses one IPv6 address or returns an explicit non-selection result.
4. Cloudflare current state is queried.
5. The planner decides `create`, `update`, `delete`, or `noop`.
6. Optional apply mutates Cloudflare state and updates workspace state files.

## Module boundaries

- `arbor_ddns.workspace`
  - loads and validates workspace source files
  - manages entry CRUD
  - renders derived artifacts
  - aggregates status and doctor output
- `arbor_ddns.discovery`
  - collects IPv6 candidate addresses from PVE
  - contains address-selection logic
  - never calls DNS APIs
- `arbor_ddns.dns`
  - contains the Cloudflare provider and the generic planner
  - never decides which guest IP is better
- `arbor_ddns.sync`
  - performs thin orchestration for plan and sync-once
  - operates on resolved workspace entries
- `arbor_ddns.systemd`
  - renders unit files
  - installs, uninstalls, and queries systemd units
- `arbor_ddns.config`
  - app-level runtime defaults
  - not the main user editing surface

## Workspace as the source of truth

The primary editing surface is the workspace directory:

- `workspace.yaml`: zone-level and instance-level settings
- `entries.yaml`: managed entry list
- `rendered/`: generated artifacts
- `runtime/`: workspace-local logs and runtime files
- `state/`: apply and managed-record tracking

The older single inventory-style model is no longer the primary workflow.

## Cloudflare-only scope

The current implementation supports Cloudflare only. Provider abstractions remain clean, but user-facing docs and commands intentionally describe only the Cloudflare path.

## Future expansion

The workspace and entry services are designed so that future MCP or other machine-oriented integrations can call them directly without scraping CLI text output.
