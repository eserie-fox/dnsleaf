# Discovery

Discovery is responsible for gathering candidate addresses from dynamic targets. It never writes DNS state directly.

## Local backend

The local backend runs on the machine currently executing dnsleaf:

```text
ip -o addr show
```

It discovers host-local IPv4 and IPv6 candidates without requiring a fake guest id.

## LXC backend

The LXC backend runs:

```text
pct exec <ctid> -- sh -lc "ip -o addr show"
```

The output is parsed with the same generic Linux `ip -o addr show` parser used by local discovery.

Parsed candidates keep:

- interface
- address
- family
- prefix length
- source backend
- optional scope
- optional state flags from `ip addr`

Metadata pairs such as `proto kernel_ra` are ignored instead of being mixed into the state-flag list.

## VM backend

The VM backend runs:

```text
qm agent <vmid> network-get-interfaces
```

Linux and Windows Guests both use `source_kind: vm` and this same backend. The parser accepts the
standard interface list plus existing PVE `result` and QGA `return` wrappers, names with spaces and
non-ASCII characters, and interfaces without addresses. Malformed top-level responses fail discovery;
invalid individual items are skipped with diagnostics. Scoped link-local addresses remain filtered,
and scope identifiers are never published.

The [QEMU protocol reference](https://www.qemu.org/docs/master/interop/qemu-ga-ref.html#command-guest-network-get-interfaces)
defines the shared address/interface fields for Windows and platforms with `getifaddrs`.
Coverage in this release uses clearly labeled synthetic Windows fixtures, alongside Linux tests;
no live Windows/PVE acceptance is claimed.

The Guest agent must be installed and running inside the VM, and PVE agent communication must be
enabled. Follow the current [official PVE guidance](https://pve.proxmox.com/pve-docs/chapter-qm.html#qm_qemu_agent)
and [Windows VirtIO guidance](https://pve.proxmox.com/wiki/Windows_VirtIO_Drivers). PVE documents the
VM Options setting and a fresh VM start for communication-setting changes. These are operator
prerequisites; dnsleaf does not change Guest settings or install a Guest-side updater.
The [official documentation source](https://github.com/proxmox/pve-docs/blob/master/qm.adoc#qemu-guest-agent)
also describes these requirements.

Read-only verification from the PVE host, substituting your VM ID:

```bash
qm status 201
qm config 201
qm agent 201 ping
qm agent 201 network-get-interfaces
dnsleaf discover vm 201 --family both --workspace /absolute/workspace --json
```

Execution/agent failures retain useful command context; dnsleaf does not guess a localized error's
cause or append sudo advice to every failure. Successful discovery with no acceptable address and
ambiguous selection are separate results. Enrollment in `entries.yaml` is a separate operator action;
adding Windows capability does not enroll existing Guests.

## Selection rules

The default IPv6 selector:

- rejects loopback
- rejects link-local
- rejects ULA
- rejects other non-global IPv6 addresses
- rejects candidates marked `deprecated`, `tentative`, or `dadfailed`
- prefers a single healthy `/128` after filtering
- otherwise prefers a single stable candidate after filtering
- refuses to guess when multiple equally plausible candidates remain

This means deprecated or otherwise unusable `/128` candidates are filtered out before ranking, so they cannot outrank a healthy global `/64`.

The default IPv4 selector:

- rejects private, CGNAT, link-local, loopback, multicast, unspecified, and other non-global addresses
- prefers a single `/32`
- refuses to guess when multiple usable public candidates remain

The selection result keeps:

- filtered candidates and reasons
- usable but non-selected candidates
- final status and reason

This makes logs and diagnostics more useful when selection is ambiguous or empty.

## Static entries

Static entries do not use discovery at all. They carry explicit operator-provided values and go directly to desired-record planning.

## Limits and per-run snapshots

Standard QGA address data does not establish all address lifetimes, deprecation, temporary-address
status, or route preference. A `/128` or embedded EUI-64 preference is a heuristic, not proof of
stability or external reachability. Multiple equally plausible global addresses remain ambiguous;
inspect the candidates and selection reasons. dnsleaf preserves remote DNS for configured targets
when it cannot select an address. This release does not alter global IPv6 policy or Guest privacy
addressing.

Every address-discovery subprocess has a finite `discovery.timeout_seconds` limit (package default
30 seconds). A sync run queries each Guest/source once, even if it supplies node and multiple service
names or both families. Failed results are also shared within that run. Selection does not mutate the
raw snapshot, and a subsequent run always queries afresh. Provider plans and responses are not cached.

Low-level discovery follows the same [workspace search](configuration.md#workspace-discovery) as
other commands. Outside-workspace mode requires genuine absence; incomplete workspaces and
inspection/validation errors are reported instead. JSON goes to stdout, diagnostics to stderr, with
one nonzero exit for discovery failure or unresolved selection.
