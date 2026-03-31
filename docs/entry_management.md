# Entry Management

Operators manage guest targets through `entries.yaml` and the `entry` CLI commands.

All `entry` commands default `--workspace` to the current directory, so `cd <workspace>` is the normal operator path.

## Entry schema

Each entry contains:

- `name`
- `source_kind`
- `source_id`
- `fqdn`
- `record_type`
- `selection_policy`
- `enabled`
- optional `ttl`
- optional `proxied`
- optional `description`

## Supported record types

Current dynamic discovery only supports `AAAA`.

`A` is reserved in schema for future expansion but is rejected during workspace validation in this round.

## CLI

### List entries

```bash
uv run arbor-ddns entry list --workspace ./workspaces/example-zone
cd ./workspaces/example-zone && uv run arbor-ddns entry list
```

### Add entries

```bash
uv run arbor-ddns entry add lxc --workspace ./workspaces/example-zone --id 101 --fqdn host.example.com --name web
uv run arbor-ddns entry add vm  --workspace ./workspaces/example-zone --id 201 --fqdn vm.example.com   --name guest
```

### Update entries

```bash
uv run arbor-ddns entry update web --workspace ./workspaces/example-zone --fqdn new.example.com --ttl 60
```

### Enable or disable

```bash
uv run arbor-ddns entry enable web --workspace ./workspaces/example-zone
uv run arbor-ddns entry disable web --workspace ./workspaces/example-zone
```

### Remove

```bash
uv run arbor-ddns entry remove web --workspace ./workspaces/example-zone
```

## Safety semantics

Removing an entry only edits `entries.yaml`.

It does not immediately delete the remote Cloudflare record.

Remote deletion only happens later if prune is explicitly enabled and the record is still present in `managed-records.json`.
