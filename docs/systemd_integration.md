# systemd Integration

`arbor-ddns` can manage one timer and one oneshot service per workspace.

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

## Scope

This round only supports system-level systemd management.

User-level systemd units are intentionally out of scope.
