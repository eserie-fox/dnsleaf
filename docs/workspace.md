# Workspace

A workspace is one DDNS management instance for one zone.

## Directory layout

Recommended layout:

```text
<workspace>/
  workspace.yaml
  entries.yaml
  secrets/
    README.txt
    cloudflare_api_token.txt
  rendered/
    effective-workspace.json
    desired-records.json
    systemd/
      arbor-ddns-<workspace>.service
      arbor-ddns-<workspace>.timer
  runtime/
    logs/
      arbor-ddns.log
    run/
  state/
    last-apply.json
    managed-records.json
```

## Source files

### `workspace.yaml`

Contains workspace-level settings:

- `config_version`
- `workspace_name`
- `provider`
- `zone_name`
- optional `zone_id`
- `api_token_file`
- `default_ttl`
- `default_proxied`
- `systemd`
- `apply`

`api_token_file` may be relative. Relative paths resolve against the workspace root at runtime.

### `entries.yaml`

Contains the user-maintained entry list.

Each entry describes:

- the source kind (`lxc`, `vm`, or `static`)
- the guest identifier for dynamic entries
- the target fqdn
- the family intent: `ipv4`, `ipv6`, or `both`
- the selection policy for dynamic entries
- enable/disable state
- optional ttl and proxied overrides
- optional static IP values for static entries

## Command semantics

All workspace-aware commands default `--workspace` to the current directory. A common operator workflow is:

```bash
cd <workspace>
arbor-ddns validate
arbor-ddns plan
arbor-ddns apply
```

### `init`

- creates the workspace directory if missing
- allows an existing empty directory
- rejects a non-empty directory
- writes starter `workspace.yaml`, `entries.yaml`, and secret guidance
- creates `rendered/`, `runtime/`, `runtime/logs/`, `runtime/run/`, and `state/`

### `validate`

- loads both source files
- validates workspace and entry schema
- resolves relative token-file paths
- checks that the token file exists, is readable, and is non-empty
- rejects old `record_type`-based entry files instead of auto-migrating them

### `render`

- validates the workspace
- writes rendered JSON artifacts
- writes rendered systemd unit files
- expands `family=both` into separate rendered `A` and `AAAA` desired-record specs
- does not call Cloudflare
- does not install systemd units

### `apply`

- validates the workspace
- renders artifacts
- installs or updates systemd units
- runs `daemon-reload`
- enables and restarts the timer
- records `last-apply.json`
- optionally runs one immediate sync
- never deletes remote Cloudflare records unless prune is explicitly enabled

### `status`

- shows workspace metadata
- shows entry counts
- shows rendered artifact presence
- shows runtime and log-file presence
- shows managed-record counts
- shows `last-apply.json`
- shows service/timer status

### `doctor`

- performs read-only workspace checks
- reports missing files, token-file issues, command availability, runtime/log writability, and systemd writability

### `uninstall`

- stops the workspace service and timer when possible
- disables the timer
- removes installed unit files
- runs `daemon-reload`
- removes generated `rendered/` and `runtime/`
- keeps `workspace.yaml`, `entries.yaml`, `secrets/`, and `state/`
- preserves `state/managed-records.json` and `state/last-apply.json` for later review or re-apply
- never deletes remote Cloudflare records
- prints a manual `rm -rf <workspace>` hint if you want to remove the workspace later

### `uninstall --purge`

- performs the normal uninstall flow
- then removes the entire workspace directory
- uses conservative path guards to avoid deleting broad or dangerous paths
