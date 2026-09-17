# Configuration

A workspace manages one Cloudflare zone through `workspace.yaml` and `entries.yaml`.
## Workspace discovery

Precedence is explicit `--workspace` / `-w`, then a non-empty `DNSLEAF_WORKSPACE` environment
variable, then automatic search. An omitted option is distinct from `--workspace .`; explicit `.`
overrides the environment. Paths expand `~` and normalize to absolute resolved directories.
`DNSLEAF_WORKSPACE` is only an environment variable: no marker file or aliases are used.

Automatic bases are the current directory, each ancestor nearest to farthest including filesystem
root, then the user's home if not already visited. For **each** base:

1. Inspect immediate child directories sorted lexicographically by name.
2. Inspect the base itself.
3. Continue only if no complete candidate has been selected.

The first complete candidate wins, including among multiple siblings. Bases and candidates are
deduplicated after normalization. A direct-child directory symlink can identify a candidate; its
resolved target is checked once without recursively searching its descendants. There is no recursive,
XDG, registry, or named-directory fallback.

The required source set is exactly `workspace.yaml` and `entries.yaml`. Token files, secrets guides,
state, logs, rendered output and systemd installation are not location markers.

- Neither required filename: silently ignore the directory.
- One required filename: warn that it is a possibly incomplete workspace (another project may use
  the same filename), list the missing file, and continue. Warnings stay visible on stderr even if a
  later candidate succeeds or logging is file-only.
- Both regular readable source files: select and load once. YAML, schema, semantic and relevant
  runtime validation failures are fatal for that selected workspace; no later candidate is tried.
- Permission errors, directories/FIFOs/devices in place of files, and other inspection errors fail
  with path context. Only confirmed absence counts as a missing file. Disappearance after selection
  is a load error, not a reason to search again.

Explicit and environment paths are authoritative: dnsleaf neither searches their children nor
replaces an invalid selection. On automatic failure, the diagnostic lists the order, checked paths,
incomplete candidates and missing files, and suggests `--workspace`, `DNSLEAF_WORKSPACE`, or
`dnsleaf init DIRECTORY`. Low-level `discover` uses outside-workspace defaults only when there was
no explicit/environment selection, no complete or partial candidate, and no filesystem error.
`status` and `doctor` retain load diagnostics and return failure for invalid selected configurations.

Example deployment (names are examples, not special cases):

```text
/root/
  ddns-config/workspace.yaml
  ddns-config/entries.yaml
  dnsleaf-backups/backup-2026-09-17/workspace.yaml
  dnsleaf-backups/backup-2026-09-17/entries.yaml
```

From `/root`, dnsleaf finds `/root/ddns-config` without inspecting the nested backup. A complete
backup placed directly among searched siblings is a normal first-match candidate. Use an explicit
workspace when a particular directory is intended.

Example diagnostics:

```text
warning=possibly incomplete workspace /work/a: missing entries.yaml; another project may use the same filename
error=workspace /work/b, file /work/b/workspace.yaml: invalid YAML in /work/b/workspace.yaml at line 2, column 1
```

`init DIRECTORY` always creates the supplied directory, independent of discovery/environment.
Help/version require no workspace or credentials. Existing deployments need no move or
reinitialization. Systemd retains an explicit absolute workspace and the installing Python environment.

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
- [`discovery.json`](../src/dnsleaf/config_defaults/discovery.json) (shared discovery limit)
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
| `discovery.timeout_seconds` | Finite positive per-command address-discovery timeout; default `30.0` seconds |
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
(`stdout`, `stderr`, or `none`). CLI workspace logging redirects a configured stdout stream to stderr
to keep report stdout machine-readable. Workspace defaults use a daily file with a stable
`runtime/logs/dnsleaf.log` symlink. `file_path: null` disables file logging. Non-workspace defaults
use stderr. CLI entrypoints own logging contexts; services use ordinary standard-library loggers.

## Entries

An operator-supplied entries document must be a mapping with an explicit `entries` list.
Empty, comment-only, null, or incomplete documents (including `{}`) fail validation before DNS
planning, regardless of the prune setting. To intentionally manage no desired records, use:

```yaml
config_version: 2
entries: []
```

This explicit empty list preserves remote records when pruning is disabled. With managed-record
pruning enabled, previously tracked records are eligible for deletion; untracked records remain
untouched. `init` generates this valid empty-list form from the packaged defaults.

An enabled entry protects its normalized FQDN and record type from pruning, even if historical state
is stale or discovery cannot select an address. Renaming an entry keeps ownership of its existing
remote record. Removing a target or disabling its entry can make it eligible for pruning; changing
a dual-stack entry to IPv4-only retires only its AAAA target. See [DNS sync](dns_sync.md#prune-behavior).

See [entry management](entry_management.md) for CLI examples and the complete source shapes.
`source_kind` is `lxc`, `vm`, `local`, or `static`; `family` is `ipv4`, `ipv6`, or `both`.
Names must be unique independently of DNS targets. Two enabled entries cannot manage the same
normalized FQDN + record type: FQDN comparison ignores case and trailing dots, and record types are
canonicalized. `family: both` owns both A and AAAA and conflicts with either overlapping family.
Separate A/AAAA entries at one name, multiple names from one Guest, and disabled duplicates are
allowed. Entry add/update/enable validates the proposed full document before atomic replacement.
Dynamic entries require `selection_policy`; guest entries also need `source_id`.
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

## Command snapshots and discovery limits

Each command selects and loads one source configuration snapshot shared by logging, validation and
operations, including apply's immediate sync. State loading and atomic persistence remain explicit.
Within a sync run, each distinct `(source_kind, source_id)` has one raw discovery snapshot; all local
entries share one local source. Successes and failures are reused. Family selection and provider
planning remain independent per entry. The next run queries again, even with the same runner.

`discovery.timeout_seconds` bounds local `ip`, `pct`, and `qm` execution. Its finite positive default
comes from shared package resources, so older YAML needs no new field. The limit does not apply to
systemd lifecycle commands. A timed-out Guest yields error outcomes, independent entries continue,
and configured targets stay protected from prune. No repeated automatic attempts occur in that run.
