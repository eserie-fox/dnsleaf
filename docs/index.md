# Documentation Index

`arbor-ddns` manages one workspace per DNS zone. The workspace is the user-facing source of truth, and the CLI follows the `init -> validate -> render -> apply -> status` workflow, with `uninstall` for local cleanup and `runtime/logs/arbor-ddns.log` for workspace-local logs.

The current implementation supports:

- dynamic PVE-backed `A`, `AAAA`, and dual-stack entries
- explicit static IPv4, IPv6, and dual-stack entries
- Cloudflare-only DNS sync

Documents:

- [Architecture Overview](architecture_overview.md)
- [Runtime Config](runtime_config.md)
- [Workspace](workspace.md)
- [Entry Management](entry_management.md)
- [Discovery](discovery.md)
- [DNS Sync](dns_sync.md)
- [systemd Integration](systemd_integration.md)
- [Development Constraints](development_constraints.md)
