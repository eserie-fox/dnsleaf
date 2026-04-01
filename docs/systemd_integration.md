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

If the console script is unavailable in the runtime environment, the generated unit falls back to `python -m arbor_ddns ...`. This matches the same module entrypoint used by the CLI `--sudo` fallback.

## Apply behavior

`apply` performs:

1. validate workspace
2. render artifacts
3. install service and timer into `workspace.yaml -> paths.systemd_unit_dir`
4. run `workspace.yaml -> paths.systemctl_bin daemon-reload`
5. run `workspace.yaml -> paths.systemctl_bin enable <timer>`
6. run `workspace.yaml -> paths.systemctl_bin restart <timer>`
7. write `state/last-apply.json`
8. optionally run one immediate sync

`apply` does not uninstall or delete remote records. It only installs or refreshes the local systemd integration and optionally runs a sync.

`apply` usually needs root privileges because it writes system-level unit files and invokes `systemctl`. If you are not root but do have `sudo`, prefer:

```bash
arbor-ddns apply --workspace <workspace> --sudo
```

This keeps the current command shape and re-executes it through the current Python environment, which is safer than assuming plain `sudo arbor-ddns ...` will resolve the same script.

## Naming

By default:

- service: `arbor-ddns-<workspace-name>.service`
- timer: `arbor-ddns-<workspace-name>.timer`

Explicit names can be set in `workspace.yaml` if required.

The unit directory and `systemctl` command are also workspace-owned:

- `paths.systemctl_bin`
- `paths.systemd_unit_dir`

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
runtime/logs/arbor-ddns.log -> runtime/logs/arbor-ddns-YYYY-MM-DD.log
```

The stable symlink points to the current daily file, and older daily files are pruned by the configured retention window.

This file log is the default destination for workspace logger output. Any normal stdout or stderr emitted by the command can still be captured by the systemd journal.

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
