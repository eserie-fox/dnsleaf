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
- optional `selection_policy` for dynamic entries
- optional `ttl`
- optional `proxied`
- optional `description`
- optional `static_ipv4`
- optional `static_ipv6`

Validation rules:

- `source_kind=lxc|vm` requires `source_id` and `selection_policy`
- `source_kind=local` requires `selection_policy` and forbids `source_id`
- `source_kind=static` forbids `source_id` and `selection_policy`
- `family=ipv4` manages one `A` record flow
- `family=ipv6` manages one `AAAA` record flow
- `family=both` manages two independent record flows
- static entries must provide matching static values for the chosen family
- local entries are dynamic entries that discover IPs from the machine running arbor-ddns
- old `record_type`-based entry files are rejected instead of being auto-converted

`ttl` accepts either a positive integer or `auto`.

- `auto` maps to Cloudflare automatic TTL
- if the effective proxy state is `true`, the provider-facing TTL is forced to Cloudflare automatic TTL

`proxied` is tri-state at the config level:

- `true` explicitly enables Cloudflare proxying
- `false` explicitly disables Cloudflare proxying
- omitted or `null` inherits the workspace default; if the resolved value is `null`, arbor-ddns preserves the current Cloudflare-side proxy state

CLI semantics mirror those config states:

- `--proxied` writes an explicit `true` override
- `--no-proxied` writes an explicit `false` override
- `entry update --inherit-proxied` removes the entry-level override and returns to inheriting the workspace default

## CLI

### List entries

```bash
arbor-ddns entry list --workspace ./workspaces/example-zone
cd ./workspaces/example-zone && arbor-ddns entry list
```

### Add dynamic entries

```bash
arbor-ddns entry add local --workspace ./workspaces/example-zone --fqdn self.example.com --name self --family both
arbor-ddns entry add lxc --workspace ./workspaces/example-zone --id 101 --fqdn host.example.com --name web --family both
arbor-ddns entry add vm  --workspace ./workspaces/example-zone --id 201 --fqdn vm.example.com   --name guest --family ipv6
arbor-ddns entry add lxc --workspace ./workspaces/example-zone --id 101 --fqdn host.example.com --name web --family both --ttl auto
arbor-ddns entry add lxc --workspace ./workspaces/example-zone --id 101 --fqdn host.example.com --name web --family both --no-proxied
```

### Add static entries

```bash
arbor-ddns entry add static \
  --workspace ./workspaces/example-zone \
  --fqdn edge.example.com \
  --name edge \
  --family both \
  --ipv4 93.184.216.34 \
  --ipv6 2408:8266:5003:506a::88
```

### Update entries

```bash
arbor-ddns entry update web --workspace ./workspaces/example-zone --family ipv4 --ttl 60
arbor-ddns entry update web --workspace ./workspaces/example-zone --ttl auto
arbor-ddns entry update web --workspace ./workspaces/example-zone --proxied
arbor-ddns entry update web --workspace ./workspaces/example-zone --no-proxied
arbor-ddns entry update web --workspace ./workspaces/example-zone --inherit-proxied
arbor-ddns entry update edge --workspace ./workspaces/example-zone --ipv6 2408:8266:5003:506a::99
```

### Enable or disable

```bash
arbor-ddns entry enable web --workspace ./workspaces/example-zone
arbor-ddns entry disable web --workspace ./workspaces/example-zone
```

### Remove

```bash
arbor-ddns entry remove web --workspace ./workspaces/example-zone
```

## Safety semantics

Removing an entry only edits `entries.yaml`.

It does not immediately delete the remote Cloudflare record.

Remote deletion only happens later if prune is explicitly enabled and the record is still present in `managed-records.json`.

## Migration

To stop arbor-ddns from overwriting manual Cloudflare proxy toggles by default:

- set `workspace.yaml.default_proxied: null`
- remove or set `entries.yaml[].proxied: null` for entries that should stop explicitly managing proxy state
- or use `arbor-ddns entry update <name> --inherit-proxied` to clear an existing entry-level override

Existing explicit `proxied: true` and `proxied: false` values remain fully managed.
