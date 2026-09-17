# Entry Management

Operators manage guest targets through `entries.yaml` and the `entry` CLI commands.

All `entry` commands use explicit `--workspace`, then `DNSLEAF_WORKSPACE`, then the shared
children-before-base automatic search. Use `-w .` to select the current directory explicitly.

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
- local entries are dynamic entries that discover IPs from the machine running dnsleaf
- old `record_type`-based entry files are rejected instead of being auto-converted

`ttl` accepts either a positive integer or `auto`.

- `auto` maps to Cloudflare automatic TTL
- if the effective proxy state is `true`, the provider-facing TTL is forced to Cloudflare automatic TTL

`proxied` is tri-state at the config level:

- `true` explicitly enables Cloudflare proxying
- `false` explicitly disables Cloudflare proxying
- omitted or `null` inherits the workspace default; if the resolved value is `null`, dnsleaf preserves the current Cloudflare-side proxy state

CLI semantics mirror those config states:

- `--proxied` writes an explicit `true` override
- `--no-proxied` writes an explicit `false` override
- `entry update --inherit-proxied` removes the entry-level override and returns to inheriting the workspace default

## CLI

### List entries

```bash
dnsleaf entry list --workspace ./workspaces/example-zone
cd ./workspaces/example-zone && dnsleaf entry list
```

### Add dynamic entries

```bash
dnsleaf entry add local --workspace ./workspaces/example-zone --fqdn self.example.com --name self --family both
dnsleaf entry add lxc --workspace ./workspaces/example-zone --id 101 --fqdn host.example.com --name web --family both
dnsleaf entry add vm  --workspace ./workspaces/example-zone --id 201 --fqdn vm.example.com   --name guest --family ipv6
dnsleaf entry add lxc --workspace ./workspaces/example-zone --id 101 --fqdn host.example.com --name web --family both --ttl auto
dnsleaf entry add lxc --workspace ./workspaces/example-zone --id 101 --fqdn host.example.com --name web --family both --no-proxied
```

### Add static entries

```bash
dnsleaf entry add static \
  --workspace ./workspaces/example-zone \
  --fqdn edge.example.com \
  --name edge \
  --family both \
  --ipv4 192.0.2.10 \
  --ipv6 2001:db8::10
```

### Update entries

```bash
dnsleaf entry update web --workspace ./workspaces/example-zone --family ipv4 --ttl 60
dnsleaf entry update web --workspace ./workspaces/example-zone --ttl auto
dnsleaf entry update web --workspace ./workspaces/example-zone --proxied
dnsleaf entry update web --workspace ./workspaces/example-zone --no-proxied
dnsleaf entry update web --workspace ./workspaces/example-zone --inherit-proxied
dnsleaf entry update edge --workspace ./workspaces/example-zone --ipv6 2001:db8::20
```

### Enable or disable

```bash
dnsleaf entry enable web --workspace ./workspaces/example-zone
dnsleaf entry disable web --workspace ./workspaces/example-zone
```

### Remove

```bash
dnsleaf entry remove web --workspace ./workspaces/example-zone
```

## Safety semantics

Removing an entry only edits `entries.yaml`.

It does not immediately delete the remote Cloudflare record.

Remote deletion only happens later if prune is explicitly enabled and the record is still present in `managed-records.json`.

## Migration

To stop dnsleaf from overwriting manual Cloudflare proxy toggles by default:

- set `workspace.yaml.default_proxied: null`
- remove or set `entries.yaml[].proxied: null` for entries that should stop explicitly managing proxy state
- or use `dnsleaf entry update <name> --inherit-proxied` to clear an existing entry-level override

Existing explicit `proxied: true` and `proxied: false` values remain fully managed.

Enabled entries must own unique normalized FQDN + record type targets. Name uniqueness is checked
separately. Case/trailing-dot differences do not create independent DNS targets. `both` conflicts
with either overlapping family, while separate A and AAAA entries are allowed. Disabled duplicates
are allowed until enabled. Add/update/enable validates the full proposed document before writing.

All entry commands use the shared [workspace discovery](configuration.md#workspace-discovery).
Multiple names can share a VM, including a Windows Guest through standard QGA; discovery is reused
within one run, with independent family selection and DNS planning for each entry.
