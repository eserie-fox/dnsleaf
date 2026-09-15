# DNS Sync

The current DNS provider scope is Cloudflare only.

## Provider responsibilities

The Cloudflare provider is responsible for:

- verifying token and zone access
- resolving `zone_id` from `zone_name` when needed
- listing current DNS records
- creating records
- updating records
- deleting records
- mapping Cloudflare API responses into project models

The provider does not choose guest IP addresses.

Cloudflare TTL and proxy behavior:

- API TTL `1` means automatic TTL
- proxied records use Cloudflare automatic TTL
- dnsleaf therefore treats `auto` as TTL `1`
- when the desired proxy state is explicitly `true`, dnsleaf compares and applies the provider-effective TTL `1`
- when the desired proxy state is unmanaged (`proxied: null`) and the current Cloudflare record is already proxied, dnsleaf ignores the forced auto-TTL mismatch instead of churning the record

## Planner responsibilities

The planner compares:

- current provider state
- desired single-record state for one concrete `A` or `AAAA` flow

It returns deterministic changes:

- `create`
- `update`
- `delete`
- `noop`

When a workspace entry has `family=both`, the runner simply constructs two independent desired records and sends them through the same planner.

`proxied` is only part of the managed desired state when it is explicitly `true` or `false`.

- explicit `true` or `false`: planner/provider enforce proxy state
- `null`: planner/provider preserve the current remote proxy state

## Verify flow

`dnsleaf provider verify --workspace <dir>` checks:

1. token file exists and is readable
2. token is non-empty
3. Cloudflare authentication works
4. the zone can be resolved
5. DNS record listing succeeds

## Zone behavior

- if `zone_id` is configured, it is used directly
- if `zone_id` is empty and `zone_name` is set, the provider resolves the zone id through the Cloudflare API
- resolved zone ids are cached in memory for the current process

## Token handling

The token is never embedded directly in workspace source config.

The workspace stores only `api_token_file`, and the provider reads and strips the file contents at runtime.

## Preserve-mode semantics

If a workspace or entry resolves to `proxied: null`:

- create/update requests omit the `proxied` field
- existing Cloudflare proxy status is preserved on update
- TTL remains managed, except that a currently proxied remote record's forced automatic TTL does not trigger a pointless update by itself

## CNAME conflict handling

If the target name already has a `CNAME`, the provider raises a clear error instead of silently attempting an invalid `A` or `AAAA` mutation.

## Prune behavior

Prune is disabled by default.

When enabled, prune only targets records that:

- were previously tracked in `state/managed-records.json`
- have a DNS target (case-insensitive FQDN without its trailing dot, plus record type) that no
  enabled entry currently configures
- still have a usable `record_id`

Untracked zone records are never deleted by prune.

Current configured targets take precedence over cached `stale` state and entry labels. Re-enabling
or renaming an entry does not authorize deletion of a still-desired record. Protection does not
depend on successful address discovery or provider planning: unavailable, ambiguous, or failed
discovery preserves the target. IPv4 and IPv6 are independent; changing `both` to `ipv4` can retire
the tracked AAAA record while protecting A.

After applied synchronization, ownership follows the current entry label and remote record ID,
without keeping conflicting stale aliases of that record. A retained record keeps its original
ownership timestamp. An explicit empty entries list still allows intentional tracked-record pruning;
incomplete entries documents fail validation before planning.

## Ambiguous remote records

When multiple remote records share the requested name and type, normal synchronization reports an
error and preserves every record, including when one already matches the desired address.
It does not pick a record arbitrarily or remove duplicates. Inspect these records manually.
Deletion planning is used only by the managed-state prune path.
