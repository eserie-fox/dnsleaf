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

- the guest source (`lxc` or `vm`)
- the guest identifier
- the target fqdn
- the record type
- the selection policy
- enable/disable state
- optional ttl and proxied overrides

## Command semantics

### `init`

- creates the workspace directory if missing
- allows an existing empty directory
- rejects a non-empty directory
- writes starter `workspace.yaml`, `entries.yaml`, and secret guidance

### `validate`

- loads both source files
- validates workspace and entry schema
- resolves relative token-file paths
- checks that the token file exists, is readable, and is non-empty

### `render`

- validates the workspace
- writes rendered JSON artifacts
- writes rendered systemd unit files
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

### `status`

- shows workspace metadata
- shows entry counts
- shows rendered artifact presence
- shows managed-record counts
- shows `last-apply.json`
- shows service/timer status

### `doctor`

- performs read-only workspace checks
- reports missing files, token-file issues, command availability, and systemd writability
