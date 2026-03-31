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

## Verify flow

`arbor-ddns provider verify --workspace <dir>` checks:

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

## CNAME conflict handling

If the target name already has a `CNAME`, the provider raises a clear error instead of silently attempting an invalid `A` or `AAAA` mutation.

## Prune behavior

Prune is disabled by default.

When enabled, prune only targets records that:

- were previously tracked in `state/managed-records.json`
- are no longer part of the current desired workspace state
- still have a usable `record_id`

Untracked zone records are never deleted by prune.
