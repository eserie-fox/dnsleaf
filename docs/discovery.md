# Discovery

Discovery is responsible for gathering candidate addresses from PVE guests. It never writes DNS state directly.

## LXC backend

The LXC backend runs:

```text
pct exec <ctid> -- sh -lc "ip -6 -o addr show"
```

The output is parsed into normalized IPv6 candidates with:

- interface
- address
- prefix length
- source backend
- optional scope
- optional flags

## VM backend

The VM backend runs:

```text
qm agent <vmid> network-get-interfaces
```

It reads the QEMU guest agent JSON and extracts IPv6 address candidates from the interface list.

## Selection rules

The default selector:

- rejects loopback
- rejects link-local
- rejects ULA
- rejects other non-global IPv6 addresses
- prefers a single `/128`
- otherwise prefers a single stable candidate
- refuses to guess when multiple equally plausible candidates remain

The selection result keeps:

- filtered candidates and reasons
- usable but non-selected candidates
- final status and reason

This makes logs and diagnostics more useful when selection is ambiguous or empty.
