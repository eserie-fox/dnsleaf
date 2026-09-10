# Configuration

A workspace manages one Cloudflare zone through `workspace.yaml` and `entries.yaml`.
Workspace commands use `--workspace` (or `-w`), defaulting to the current directory.
There is no global config file, workspace registry, environment-variable search, or parent-directory search.

## Loading and resources

`WorkspaceConfig` and `EntriesFile` in `dnsleaf.workspace.models` provide `from_defaults()`,
`from_file(path)`, and `from_mapping(data)`. `OutsideWorkspaceConfig` in
`dnsleaf.config.outside_workspace` provides the same API for internal defaults and JSON overrides;
it is not a separate operator-facing configuration layer.

Loading always reads package JSON defaults, reads the override, merges, then validates with
Pydantic v2. Mappings merge recursively. Lists, scalars, booleans, and null replace their base value;
lists never concatenate. Unknown fields and wrongly typed operational scalars fail validation.
YAML TTL values must be integers or `auto`, not quoted numeric strings. Error messages omit input
values to avoid exposing accidentally embedded credentials.

The authoritative defaults are:

- [`workspace.json`](../src/dnsleaf/config_defaults/workspace.json)
- [`entries.json`](../src/dnsleaf/config_defaults/entries.json)
- [`outside_workspace.json`](../src/dnsleaf/config_defaults/outside_workspace.json)

`templates/layout.json` defines initialization directories; `templates/secrets_readme.txt` provides
secret-file guidance. Initialization serializes the validated defaults as YAML, with the directory
basename used as `workspace_name`. Resources ship in both wheel and sdist and use `importlib.resources`.

## Workspace settings

`config_version` is **4**, identifying the schema, independently of the Python package version.
Earlier schemas and unknown fields are rejected. `entries.yaml` retains schema **2**.
A minimal override might contain:

```yaml
config_version: 4
workspace_name: example-zone
zone_name: example.com
api_token_file: secrets/cloudflare_api_token.txt
```

All other fields come from the package defaults. `init` writes a full initial configuration for editing.

| Field | Meaning |
| --- | --- |
| `workspace_name` | Stable name used for default systemd unit names |
| `provider` | `cloudflare` only |
| `zone_name`, `zone_id` | Zone name; an optional explicit ID avoids name lookup |
| `api_token_file` | Token file reference, never the token itself |
| `default_ttl` | Positive integer seconds or `auto` (Cloudflare API value `1`) |
| `default_proxied` | `true` or `false` manages proxy state; `null` preserves it |
| `paths` | Discovery commands, systemctl command, system unit directory |
| `systemd` | Optional unit names, timer intervals, immediate-sync preference |
| `apply.prune_managed_records` | Default prune preference; package default is disabled |
| `dnsleaf_logging` | Level, format, file path, retention days, and stream |

`paths` contains `pct_bin`, `qm_bin`, `shell_bin`, `systemctl_bin`, and `systemd_unit_dir`.
Command values are executable names or absolute paths, not shell expressions. PVE commands must
exist on the host. The timer's Python entry is bound at installation and is not configurable through PATH.

`systemd` contains `service_name`, `timer_name`, `on_boot_sec`, `on_unit_active_sec`, and
`run_sync_after_apply`. Null unit names derive `dnsleaf-<workspace_name>`.
Names must be safe single filename components; interval strings cannot contain control characters.
The only supported systemd mode is system-level.

`dnsleaf_logging` contains `level`, `format`, `file_path`, `retention_days`, and `stream`
(`stdout`, `stderr`, or `none`). Workspace defaults use a daily file with a stable
`runtime/logs/dnsleaf.log` symlink. `file_path: null` disables file logging. Non-workspace defaults
use stderr. CLI entrypoints own logging contexts; services use ordinary standard-library loggers.

## Entries

See [entry management](entry_management.md) for CLI examples and the complete source shapes.
`source_kind` is `lxc`, `vm`, `local`, or `static`; `family` is `ipv4`, `ipv6`, or `both`.
Names must be unique. Dynamic entries require `selection_policy`; guest entries also need `source_id`.
Static entries provide `static_ipv4` and/or `static_ipv6` and bypass discovery.

Entry `ttl` and `proxied` values override workspace defaults. Omitted or null entry values inherit
the workspace default. When the **resolved** proxy value is null, updates omit `proxied` and retain
the remote setting. A currently proxied remote record's forced auto TTL is also preserved.
Use `entry update NAME --inherit-proxied` to clear a boolean override.

## Runtime paths and stored state

Raw constructors never expand paths or read token contents. `WorkspaceConfig.resolve(workspace_root)`
produces runtime paths separately. Relative token, system unit directory, and log paths are based on
the workspace root, never the caller's current directory. `~` expansion occurs during resolution.
No environment-variable interpolation is performed. Log path resolution retains the stable symlink
name rather than dereferencing it into yesterday's log file.

`validate` additionally checks token readability and non-empty content. `render` writes effective JSON,
desired-record specifications, and unit files under `rendered/`; neither calls Cloudflare.

`state/managed-records.json` tracks record IDs owned by this workspace, and `state/last-apply.json`
records the local installation. Keep state when reinstalling: it defines prune ownership.
Generated files and logs are disposable; user config and secrets remain separate. Default uninstall
preserves state, config, and secrets. Purge deletes the workspace only after successful service cleanup.
