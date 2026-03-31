# Discovery

Discovery is responsible for gathering candidate addresses from PVE guests. It never writes DNS state directly.

## LXC backend

The LXC backend runs:

```text
pct exec <ctid> -- sh -lc "ip -o addr show"
```

The output is parsed into normalized IPv4 and IPv6 candidates with:

- interface
- address
- family
- prefix length
- source backend
- optional scope
- optional flags

## VM backend

The VM backend runs:

```text
qm agent <vmid> network-get-interfaces
```

It reads the QEMU guest agent JSON and extracts IPv4 and IPv6 address candidates from the interface list.

## Selection rules

The default IPv6 selector:

- rejects loopback
- rejects link-local
- rejects ULA
- rejects other non-global IPv6 addresses
- prefers a single `/128`
- otherwise prefers a single stable candidate
- refuses to guess when multiple equally plausible candidates remain

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
