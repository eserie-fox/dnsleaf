# Development Constraints

This repository intentionally stays narrow and predictable.

## Structural constraints

- The root CLI is only a command entry surface.
- `sync/runner.py` stays thin and orchestration-focused.
- Discovery backends only return candidate addresses.
- Address selection happens in discovery/selector code, not in DNS providers.
- DNS providers never guess which IP should be published.
- Workspace source files are the main user-maintained state.
- Rendered artifacts and state files are generated outputs.
- One entry may expand to two concrete record flows when `family=both`.
- Static entries bypass discovery and selection.

## Configuration constraints

- App runtime config follows the formal runtime config pattern.
- Package defaults live in `src/arbor_ddns/config_defaults/app.json`.
- Loading order is fixed: defaults -> override -> deep merge -> validate.
- Runtime-only resolution is explicit and separate from raw config loading.
- Secrets are not embedded in source config files.
- Cloudflare API tokens are read from `api_token_file`.
- Token contents must never be printed in logs or reports.

## Execution constraints

- Current execution is serial.
- Discovery command execution is centralized in `util/process.py`.
- systemd integration is system-level only in this round.
- Normal apply does not delete remote DNS records.
- Prune only targets records previously tracked by the workspace state file.
- If a tracked record cannot be deleted safely by `record_id`, it is skipped instead of guessed.
- Default uninstall is local-only cleanup and never deletes remote DNS records.
- Default uninstall keeps `state/` so managed-record ownership history survives reinstall.

## Scope constraints

- Provider scope is Cloudflare only.
- Dynamic discovery currently supports both IPv4 and IPv6.
- Static entries support explicit IPv4, IPv6, and dual-stack values.
- MCP is not implemented in this round, but the service layer is shaped to support it later.
