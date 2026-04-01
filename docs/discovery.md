# Discovery

Discovery is responsible for gathering candidate addresses from dynamic targets. It never writes DNS state directly.

## Local backend

The local backend runs on the machine currently executing arbor-ddns:

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
