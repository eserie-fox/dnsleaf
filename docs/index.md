# Documentation Index

`arbor-ddns` manages one workspace per DNS zone. The workspace is the user-facing source of truth, and the CLI follows the `init -> validate -> render -> apply -> status` workflow, with `uninstall` for local cleanup and a stable `runtime/logs/arbor-ddns.log` symlink for workspace-local logs.

The current implementation supports:

- dynamic `A`, `AAAA`, and dual-stack entries from PVE guests or the local host
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
- [Internal Release Workflow](release.md)
- [Release Notes 1.0.2](release-notes/1.0.2.md)
- [Release Notes 1.0.1](release-notes/1.0.1.md)
