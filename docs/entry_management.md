# Entry Management

Operators manage guest targets through `entries.yaml` and the `entry` CLI commands.

All `entry` commands default `--workspace` to the current directory, so `cd <workspace>` is the normal operator path.

## Entry schema

Each entry contains:

- `name`
- `source_kind`
- `fqdn`
- `family`
- `enabled`
- optional `source_id` for `lxc` and `vm`
- optional `selection_policy` for `lxc` and `vm`
- optional `ttl`
- optional `proxied`
- optional `description`
- optional `static_ipv4`
- optional `static_ipv6`

Validation rules:

- `source_kind=lxc|vm` requires `source_id` and `selection_policy`
- `source_kind=static` forbids `source_id` and `selection_policy`
- `family=ipv4` manages one `A` record flow
- `family=ipv6` manages one `AAAA` record flow
- `family=both` manages two independent record flows
- static entries must provide matching static values for the chosen family
- old `record_type`-based entry files are rejected instead of being auto-converted

## CLI

### List entries

```bash
uv run arbor-ddns entry list --workspace ./workspaces/example-zone
cd ./workspaces/example-zone && uv run arbor-ddns entry list
```

### Add dynamic entries

```bash
uv run arbor-ddns entry add lxc --workspace ./workspaces/example-zone --id 101 --fqdn host.example.com --name web --family both
uv run arbor-ddns entry add vm  --workspace ./workspaces/example-zone --id 201 --fqdn vm.example.com   --name guest --family ipv6
```

### Add static entries

```bash
uv run arbor-ddns entry add static \
  --workspace ./workspaces/example-zone \
  --fqdn edge.example.com \
  --name edge \
  --family both \
  --ipv4 93.184.216.34 \
  --ipv6 2408:8266:5003:506a::88
```

### Update entries

```bash
uv run arbor-ddns entry update web --workspace ./workspaces/example-zone --family ipv4 --ttl 60
uv run arbor-ddns entry update edge --workspace ./workspaces/example-zone --ipv6 2408:8266:5003:506a::99
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
