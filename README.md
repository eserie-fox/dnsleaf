# arbor-ddns

`arbor-ddns` is a lightweight, workspace-driven DDNS tool for PVE guests and static IP targets.
It discovers guest IPv4 and IPv6 addresses from the PVE host, selects publishable dynamic candidates, syncs `A` and `AAAA` records to Cloudflare, and can install a systemd timer for periodic runs.

Current scope:

- discovery backends: `pct exec` for LXC, `qm agent network-get-interfaces` for VMs
- address selection: public IPv4 and global IPv6, with explicit ambiguity handling
- static entries: direct IPv4, IPv6, or dual-stack values
- DNS provider: Cloudflare only
- operations model: workspace source files + rendered artifacts + state

## Install

```bash
pip install .
```

For local development, testing, and release builds, install the editable package with development extras:

```bash
pip install -e '.[dev]'
```

See [Internal Release Workflow](docs/release.md) for local build, install, and verification steps.

## Quick start

1. Initialize a workspace.

```bash
arbor-ddns init ./workspaces/example-zone
```

2. Put a Cloudflare API token into the workspace.

```bash
printf '%s\n' 'YOUR_TOKEN' > ./workspaces/example-zone/secrets/cloudflare_api_token.txt
```

3. Edit `workspace.yaml` and set at least:

- `zone_name`
- optional `zone_id`
- `api_token_file` if you want a different token path
- optional `paths` overrides if this workspace should use non-default `pct`, `qm`, `sh`, `systemctl`, or a non-default systemd unit directory
- optional `arbor_ddns_logging` overrides if you want a different workspace log path, level, stream, or retention

4. Add entries.

```bash
arbor-ddns entry add lxc \
  --workspace ./workspaces/example-zone \
  --id 101 \
  --fqdn host.example.com \
  --name web \
  --family both

arbor-ddns entry add vm \
  --workspace ./workspaces/example-zone \
  --id 201 \
  --fqdn vm.example.com \
  --name guest \
  --family ipv6

arbor-ddns entry add static \
  --workspace ./workspaces/example-zone \
  --fqdn edge.example.com \
  --name edge \
  --family both \
  --ipv4 93.184.216.34 \
  --ipv6 2408:8266:5003:506a::88
```

You can also change into the workspace and omit `--workspace` on all workspace-aware commands:

```bash
cd ./workspaces/example-zone
arbor-ddns entry list
```

5. Validate and verify provider access.

```bash
cd ./workspaces/example-zone
arbor-ddns validate
arbor-ddns provider verify
```

6. Inspect the live DNS plan, then sync once.

```bash
arbor-ddns plan --workspace ./workspaces/example-zone
cd ./workspaces/example-zone
arbor-ddns sync-once
arbor-ddns sync-once --apply
```

`family=both` is handled as two independent flows. One family may `create`, `update`, or `noop` while the other is skipped because discovery was ambiguous or had no usable candidate.

7. Render artifacts or install systemd units.

```bash
arbor-ddns render --workspace ./workspaces/example-zone
arbor-ddns apply --workspace ./workspaces/example-zone --sudo
arbor-ddns apply --workspace ./workspaces/example-zone --run-sync
```

`apply` writes or updates systemd units under `/etc/systemd/system` by default, so it typically needs root privileges. If you are not root but do have `sudo`, prefer `arbor-ddns ... --sudo` over rewriting the command manually as `sudo arbor-ddns ...`.
That target path is workspace-owned and can be changed with `workspace.yaml -> paths.systemd_unit_dir`.

Outside a workspace, only low-level `discover` uses the package-shipped outside-workspace config, which provides fallback `pct`, `qm`, `sh`, and stderr logging defaults before any workspace context exists.

## Privileges And `--sudo`

Use `--sudo` when:

- you are not running as root
- the command really needs root privileges
- you do have `sudo`
- arbor-ddns is installed from a virtualenv, uv-managed environment, or another Python environment where plain `sudo arbor-ddns ...` may not find the same script or interpreter

`arbor-ddns ... --sudo` re-executes the current command through the active CLI entry, so you do not need to manually rewrite it as a root command. The CLI preserves the current command arguments as closely as possible and prints a retry hint when a privileged command fails without `--sudo`.

Examples:

```bash
arbor-ddns apply --workspace ./workspaces/example-zone --sudo
arbor-ddns plan --workspace ./workspaces/example-zone --sudo
arbor-ddns discover lxc 101 --sudo
```

## Runtime files

Each workspace has a `runtime/` subtree for local operator artifacts:

```text
runtime/
  logs/
    arbor-ddns.log -> arbor-ddns-YYYY-MM-DD.log
    arbor-ddns-YYYY-MM-DD.log
  run/
```

`runtime/logs/arbor-ddns.log` is the stable operator-facing symlink. The actual file writes go to daily files, and old daily files are pruned by the configured retention window.

New workspaces default to `arbor_ddns_logging.stream: none`, so logger output goes to the workspace file log by default. Command results and errors still print concise summaries to stdout and stderr.

Existing workspaces keep whatever `arbor_ddns_logging.stream` value is already in `workspace.yaml`. Set it to `none` if you want the same file-only logger behavior there too.

## Uninstall

`uninstall` removes systemd installation artifacts and generated workspace runtime files without touching editable config or remote Cloudflare records.

```bash
cd ./workspaces/example-zone
arbor-ddns uninstall
```

Default uninstall removes:

- installed service and timer units
- `rendered/`
- `runtime/`

Default uninstall keeps:

- `workspace.yaml`
- `entries.yaml`
- `secrets/`
- `state/`

If you want to remove the entire workspace directory too:

```bash
arbor-ddns uninstall --workspace ./workspaces/example-zone --purge
```

## Workspace commands

- `arbor-ddns init <dir>`
- `arbor-ddns validate [--workspace <dir>]`
- `arbor-ddns render [--workspace <dir>]`
- `arbor-ddns apply [--workspace <dir>]`
- `arbor-ddns uninstall [--workspace <dir>] [--purge]`
- `arbor-ddns status [--workspace <dir>]`
- `arbor-ddns doctor [--workspace <dir>]`
- `arbor-ddns entry list|add|update|remove|enable|disable [--workspace <dir>]`
- `arbor-ddns provider verify [--workspace <dir>]`
- `arbor-ddns plan [--workspace <dir>]`
- `arbor-ddns sync-once [--workspace <dir>] [--apply]`
- `arbor-ddns discover lxc <id> [--family ipv4|ipv6|both] [--workspace <dir>]`
- `arbor-ddns discover vm <id> [--family ipv4|ipv6|both] [--workspace <dir>]`

## Testing

```bash
pytest
ruff check .
mypy src
```

## Internal Release

Local wheel and sdist build flow:

```bash
python -m build
pip install dist/arbor_ddns-1.0.1-py3-none-any.whl
arbor-ddns --version
```

For the full internal release checklist, see [docs/release.md](docs/release.md) and [1.0.1 release notes](docs/release-notes/1.0.1.md).

## Documentation

- [Docs Index](docs/index.md)
- [Architecture Overview](docs/architecture_overview.md)
- [Runtime Config](docs/runtime_config.md)
- [Workspace](docs/workspace.md)
- [Entry Management](docs/entry_management.md)
- [Discovery](docs/discovery.md)
- [DNS Sync](docs/dns_sync.md)
- [systemd Integration](docs/systemd_integration.md)
- [Development Constraints](docs/development_constraints.md)
- [Internal Release Workflow](docs/release.md)
- [Release Notes 1.0.1](docs/release-notes/1.0.1.md)
