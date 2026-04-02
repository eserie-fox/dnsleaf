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
      arbor-ddns-YYYY-MM-DD.log
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
- `paths`
- `systemd`
- `apply`
- `arbor_ddns_logging`

`api_token_file` may be relative. Relative paths resolve against the workspace root at runtime.

`config_version` is currently `3`.

`default_ttl` accepts either a positive integer or `auto`.

- `auto` maps to Cloudflare automatic TTL (`1`)
- the scaffold now defaults to `default_ttl: auto`

`default_proxied` accepts `true`, `false`, or `null`.

- `true` and `false` keep proxy state explicitly managed
- `null` means proxy state is unmanaged and Cloudflare-side proxy status is preserved on update
- the scaffold now defaults to `default_proxied: null`

### `paths`

Contains workspace-owned execution paths:

- `pct_bin`
- `qm_bin`
- `shell_bin`
- `systemctl_bin`
- `systemd_unit_dir`

These fields define how this specific workspace performs discovery and systemd integration.

`systemd_unit_dir` may be relative. Relative values resolve against the workspace root at runtime.

Command-path fields remain plain strings. They may be absolute paths or command names resolved through `PATH`.

The first three fields share the same schema as the outside-workspace config:

- `pct_bin`
- `qm_bin`
- `shell_bin`

The systemd fields exist only on the workspace side because they are workspace apply/runtime concerns.

### `arbor_ddns_logging`

Contains workspace-scoped logging settings for arbor-ddns itself:

- `level`
- `format`
- `file_path`
- `retention_days`
- `stream`

`file_path` may be relative. Relative paths resolve against the workspace root at runtime.

The default scaffold uses:

- stable path: `runtime/logs/arbor-ddns.log`
- daily target files: `runtime/logs/arbor-ddns-YYYY-MM-DD.log`
- retention: `7`
- stream: `none`

This logging schema is shared with the outside-workspace config, but the defaults differ by context: workspace scaffolds default to file-only logger output, while outside-workspace logging keeps `file_path: null` and `stream: stderr`.

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

If an entry omits `proxied`, it inherits `workspace.yaml.default_proxied`.

- if the effective value is `true` or `false`, arbor-ddns manages proxy state
- if the effective value is `null`, arbor-ddns leaves Cloudflare proxy state unchanged
- use `arbor-ddns entry update <name> --inherit-proxied` to clear an existing entry-level override and return to this inherited behavior

If an entry omits `ttl`, it inherits `workspace.yaml.default_ttl`.

- TTL values may be a positive integer or `auto`
- rendered/provider-facing TTL is always an integer
- proxied records use Cloudflare automatic TTL, so an explicit proxied end state resolves to TTL `1`

## Command semantics

All workspace-aware commands default `--workspace` to the current directory. A common operator workflow is:

```bash
cd <workspace>
arbor-ddns validate
arbor-ddns plan
arbor-ddns apply
```

If one of these commands needs root privileges and you are not root but do have `sudo`, prefer appending `--sudo`:

```bash
arbor-ddns apply --sudo
arbor-ddns plan --sudo
```

This is especially useful when arbor-ddns is installed from a virtualenv or another managed Python environment where plain `sudo arbor-ddns ...` may not resolve the same script or interpreter. The CLI re-executes the current command through the active entrypoint and prints a retry hint when you forget `--sudo`.

### `init`

- creates the workspace directory if missing
- allows an existing empty directory
- rejects a non-empty directory
- writes starter `workspace.yaml`, `entries.yaml`, and secret guidance
- creates `rendered/`, `runtime/`, `runtime/logs/`, `runtime/run/`, and `state/`
- uses typed scaffold constructors from the model layer, rather than building raw default mappings in storage

### `validate`

- loads both source files
- validates workspace and entry schema
- resolves relative token-file paths
- resolves relative `paths.systemd_unit_dir`
- resolves relative `arbor_ddns_logging.file_path`
- checks that the token file exists, is readable, and is non-empty
- rejects old `record_type`-based entry files instead of auto-migrating them

### `render`

- validates the workspace
- writes rendered JSON artifacts
- writes rendered systemd unit files
- writes the resolved workspace logging path into `rendered/effective-workspace.json`
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
- shows the resolved log path and the current symlink target when present
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

## Discovery outside a workspace

`discover lxc` and `discover vm` can still run outside a workspace for low-level debugging.

- if `--workspace` is provided, workspace paths and workspace logging are used
- if `--workspace` is omitted and the current directory is a valid workspace, that workspace is used
- otherwise `discover` falls back to the outside-workspace config for `pct`, `qm`, and `shell`

The low-level discover commands also accept `--sudo`, which is useful when guest discovery needs elevated privileges on the PVE host:

```bash
arbor-ddns discover lxc 101 --sudo
arbor-ddns discover vm 201 --sudo
```
