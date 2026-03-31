# systemd Integration

`arbor-ddns` can manage one timer and one oneshot service per workspace.

Workspace-aware commands default `--workspace` to the current directory, so a typical systemd-managed workspace flow is:

```text
cd <workspace>
arbor-ddns apply
arbor-ddns status
```

## Rendered units

`render` writes unit files under:

```text
rendered/systemd/
  arbor-ddns-<workspace>.service
  arbor-ddns-<workspace>.timer
```

The service executes one sync cycle for the workspace:

```text
arbor-ddns sync-once --workspace <abs-workspace> --apply
```

## Apply behavior

`apply` performs:

1. validate workspace
2. render artifacts
3. install service and timer into the configured systemd unit directory
4. `systemctl daemon-reload`
5. `systemctl enable <timer>`
6. `systemctl restart <timer>`
7. write `state/last-apply.json`
8. optionally run one immediate sync

`apply` does not uninstall or delete remote records. It only installs or refreshes the local systemd integration and optionally runs a sync.

## Naming

By default:

- service: `arbor-ddns-<workspace-name>.service`
- timer: `arbor-ddns-<workspace-name>.timer`

Explicit names can be set in `workspace.yaml` if required.

## Status behavior

`status` queries systemd and reports:

- load state
- unit-file state
- active state
- sub-state
- fragment path when available

If `systemctl` is unavailable, status degrades gracefully instead of crashing.

## Runtime logs

Workspace-local logs live under:

```text
runtime/logs/arbor-ddns.log
```

This file log is additive to normal stdout and stderr output. When the workspace timer runs under systemd, journal output still works as usual.

## Uninstall behavior

`uninstall` removes the installed unit files and generated workspace runtime artifacts.

Default uninstall:

- stops the service when possible
- stops and disables the timer
- removes the installed service and timer unit files
- runs `daemon-reload`
- removes `rendered/` and `runtime/`
- keeps `state/` so managed-record history survives a later reinstall
- never touches remote Cloudflare DNS records

`uninstall --purge` also removes the entire workspace directory after the normal uninstall cleanup.

## Scope

This round only supports system-level systemd management.

User-level systemd units are intentionally out of scope.
