# arbor-ddns

`arbor-ddns` is a lightweight, workspace-driven DDNS tool for PVE guests.
It discovers guest IPv6 addresses from the PVE host, selects one stable AAAA target, plans the required Cloudflare DNS changes, and can install a systemd timer for periodic sync.

The current scope is intentionally narrow:

- discovery backends: `pct exec` for LXC, `qm agent network-get-interfaces` for VMs
- address selection: IPv6-only, tuned for DNS AAAA
- DNS provider: Cloudflare only
- operations model: workspace source files + rendered artifacts + state

## Install

```bash
uv sync --python 3.11
```

## Quick start

1. Initialize a workspace.

```bash
uv run arbor-ddns init ./workspaces/example-zone
```

2. Put a Cloudflare API token into the workspace.

```bash
printf '%s\n' 'YOUR_TOKEN' > ./workspaces/example-zone/secrets/cloudflare_api_token.txt
```

3. Edit `workspace.yaml` and set at least:

- `zone_name`
- optional `zone_id`
- `api_token_file` if you want a different token path

4. Add entries.

```bash
uv run arbor-ddns entry add lxc \
  --workspace ./workspaces/example-zone \
  --id 101 \
  --fqdn host.example.com \
  --name web

uv run arbor-ddns entry add vm \
  --workspace ./workspaces/example-zone \
  --id 201 \
  --fqdn vm.example.com \
  --name guest
```

You can also change into the workspace and omit `--workspace` on all workspace-aware commands:

```bash
cd ./workspaces/example-zone
uv run arbor-ddns entry list
```

5. Validate and verify provider access.

```bash
cd ./workspaces/example-zone
uv run arbor-ddns validate
uv run arbor-ddns provider verify
```

6. Inspect the live DNS plan, then sync once.

```bash
uv run arbor-ddns plan --workspace ./workspaces/example-zone
cd ./workspaces/example-zone
uv run arbor-ddns sync-once
uv run arbor-ddns sync-once --apply
```

7. Render artifacts or install systemd units.

```bash
uv run arbor-ddns render --workspace ./workspaces/example-zone
uv run arbor-ddns apply --workspace ./workspaces/example-zone
uv run arbor-ddns apply --workspace ./workspaces/example-zone --run-sync
```

`apply` writes or updates systemd units under `/etc/systemd/system` by default, so it typically needs root privileges.

## Runtime files

Each workspace has a `runtime/` subtree for local operator artifacts:

```text
runtime/
  logs/
    arbor-ddns.log
  run/
```

The CLI still writes concise summaries to stdout and stderr. The file log is additive and is useful for later inspection from the workspace itself.

## Uninstall

`uninstall` removes systemd installation artifacts and generated workspace runtime files without touching editable config or remote Cloudflare records.

```bash
cd ./workspaces/example-zone
uv run arbor-ddns uninstall
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
uv run arbor-ddns uninstall --workspace ./workspaces/example-zone --purge
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
- `arbor-ddns discover lxc <id>`
- `arbor-ddns discover vm <id>`

## Testing

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

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
