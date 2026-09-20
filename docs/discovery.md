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
standard interface list plus existing PVE `result` and QGA `return` wrappers, hardware addresses, names with spaces and
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

## Windows DHCPv6 opt-in

`selection_policy: windows-dhcpv6` supports VM entries with `family: ipv6` or `both`. It authorizes
one fixed read-only supplementary Windows metadata query through **guest-exec**. It does not detect
Guest OS automatically. Linux, LXC, local and default-policy VM discovery retain their existing
commands. The policy is rejected for non-VM or IPv4-only entries; unknown policy names also fail
before execution. For `both`, IPv4 uses the existing public-address selector.

A `/128` is a prefix length, not DHCP provenance. Two `/128` addresses may include one DHCP address
and one RA/Random address. Default selection remains ambiguous in that case. The strict policy
requires a usable global IPv6 address in QGA **and** matched Windows evidence:

- `PrefixOrigin` and `SuffixOrigin` are both exactly `Dhcp`.
- `AddressState` is `Preferred`.
- `SkipAsSource` is the JSON boolean `false`.

It does not require `/128`: an eligible DHCP `/64` can win over an RA `/128`. RA/Random is excluded
by this policy without claiming that every such address is temporary. DHCP provenance does not
prove permanence, lifetime, routing preference or Internet reachability. There is no heuristic
fallback when evidence is unavailable.

### Prerequisites and use

Alongside a working QGA network query, the VM needs Windows PowerShell 5.1, `Get-NetIPAddress` and
`Get-NetAdapter` with access to their CIM providers, and permission/capability to execute the fixed
probe through PVE/QGA guest-exec. PowerShell 7 is not required. Blocked guest-exec or cmdlet
access is reported as a supplementary failure; dnsleaf does not alter execution policy, install
tools, change networking or start the VM. PVE's agent API documents guest execution separately from
address querying, including its `VM.GuestAgent.Unrestricted` permission.

Use synthetic ID 201 and an existing workspace path appropriate for your installation:

```bash
dnsleaf discover vm 201 --workspace /absolute/workspace \
  --family ipv6 --selection-policy windows-dhcpv6 --json
dnsleaf entry add vm --workspace /absolute/workspace --id 201 \
  --name windows-node --fqdn windows-node.example.com --family ipv6 \
  --selection-policy windows-dhcpv6 --no-proxied
dnsleaf entry update windows-node --workspace /absolute/workspace \
  --selection-policy windows-dhcpv6
```

Discover is read-only. Entry add/update changes local configuration and validates the complete
proposed entries document before saving. Enrollment is a separate operator decision after inspecting
selection evidence. `plan` and `sync-once` without `--apply` may run the fixed read-only Guest probe,
but do not change Guest configuration or remote DNS. No deployed YAML, state or systemd migration is
required; existing `default` entries remain unchanged.

### Transport and evidence contract

The readable [packaged probe](../src/dnsleaf/probes/windows_ipv6.ps1) queries active IPv6 records and
visible/hidden adapters (including virtual NICs). It joins each address's `InterfaceIndex` to adapter
hardware identity, and emits an `addresses` array with address, prefix, interface index/alias, MAC,
origins, state and SkipAsSource. Cmdlet/CIM errors terminate the probe before any partial inventory
is serialized. The host accepts an empty array, multiple records, or a single address object inside
this envelope; scalar roots are invalid.

The transport is `qm guest exec VMID --synchronous 1 --timeout N -- powershell.exe -NoProfile
-NonInteractive -EncodedCommand ...`, using the configured `qm_bin` and an argument list without a
host shell. Only package-owned source is encoded as UTF-16LE; operator data is never interpolated.
The probe writes ASCII JSON with non-ASCII UTF-16 units escaped as `\uXXXX`, so Chinese aliases and
surrogate pairs survive QGA's Base64 transport and PVE's decoding. Python parses qm's UTF-8 JSON;
it does **not** Base64-decode `out-data` again. One leading JSON BOM is tolerated. Tests simulate
this full encoding path; the PowerShell script itself has not been executed on a live Windows Guest.

PVE prints the unwrapped result, with decoded `out-data`/`err-data` and booleans represented as
booleans or integers 0/1. dnsleaf requires explicit completion, integer Guest exitcode zero and
non-truncated output. A host exit code of zero, PID-only result, absent exit status, signal, malformed
JSON or invalid field type is insufficient. Error excerpts are bounded and omit the encoded script.

Both the host subprocess bound and PVE synchronous wait reuse `discovery.timeout_seconds`
(default 30). PVE's integer wait rounds positive fractional values up to at least one second; the
host retains the precise configured bound for the entire subprocess, including waiting. PID-only
wait expiry fails without polling or restarting the probe. A host timeout does **not** prove that
the Guest process was terminated; dnsleaf issues no destructive cleanup command.

Correlation uses normalized IPv6 **plus normalized hardware/MAC identity**, with equal prefix
lengths. Interface aliases are diagnostic labels, never a substitute for identity. Every usable QGA
IPv6 address must have consistent metadata; every global Windows observation must have a matching
QGA observation. Missing identities, malformed QGA items, extra/missing addresses, prefix changes,
conflicting duplicates and inconsistent index/MAC mappings refuse selection. Identical repeated
observations of the same address on the same proven interface are deduplicated. Neither query is
atomic with the other: refusal allows a later ordinary run to obtain fresh snapshots.

Exactly one eligible address yields `selected` with reason
`unique eligible Windows-reported DHCPv6 address corroborated by QGA`. Multiple eligible addresses
or insufficient/conflicting correlation evidence yield `ambiguous`; complete consistent evidence
with no eligible DHCP address yields `no_candidate`.

### Reporting and failures

JSON retains `backend: pve_qga`, raw `candidates`, `error`, `error_stage` and `parsing_issues`.
Each IPv6 selection includes `supplementary` status/error/stage and validated address evidence,
plus filtered/non-selected candidate dispositions and the correlation/selection reason. A successful
raw query followed by failed metadata still has raw `error: null`; the supplementary error is
reported on the affected synchronization outcome. Ordinary no-candidate/ambiguity outcomes keep
the existing skipped semantics. DNS planning/application remain separate report stages.

`discover` exits nonzero if **any requested family** cannot be selected. With `both`, a selected IPv6
remains in JSON when IPv4 has only private candidates. Likewise, a metadata failure leaves a valid
IPv4 selection visible. It never relaxes public IPv4 filtering just to make a command successful.
Configured targets remain protected from prune and unresolved records retain their current values.
Other entries continue through the run.

Each run shares one raw QGA snapshot and at most one supplementary snapshot per opted-in VM,
including failures. Mixed default/strict entries work in either order without mutating shared raw
candidates. Default-only VMs never run the probe. A later run always refreshes both snapshots.

Protocol references checked for this implementation:

- [PVE qm CLI source](https://raw.githubusercontent.com/proxmox/qemu-server/master/src/PVE/CLI/qm.pm).
- [PVE execution status decoding](https://raw.githubusercontent.com/proxmox/qemu-server/master/src/PVE/QemuServer/Agent.pm)
  and [agent API schema/permissions](https://raw.githubusercontent.com/proxmox/qemu-server/master/src/PVE/API2/Qemu/Agent.pm).
- [QEMU Guest Agent protocol](https://www.qemu.org/docs/master/interop/qemu-ga-ref.html).
- [Get-NetIPAddress](https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-netipaddress?view=windowsserver2025-ps),
  [Get-NetAdapter](https://learn.microsoft.com/en-us/powershell/module/netadapter/get-netadapter?view=windowsserver2025-ps)
  and [PowerShell 5.1 invocation/encoding](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1).

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
