# systemd

Each workspace has a system-level timer and a oneshot service. Default names are
`dnsleaf-<workspace_name>.timer` and `dnsleaf-<workspace_name>.service`.
Timer intervals and optional names come from [workspace configuration](configuration.md).

`render` writes units under `rendered/systemd/` without installation or DNS access.
`apply` validates, checks state writability, renders, installs units, reloads systemd, enables and
restarts the timer, and records installation state. It optionally synchronizes immediately;
`--no-run-sync` only disables that immediate invocation. The enabled timer executes DNS writes on schedule.

## Persistent Python environment

Use the [uv tool installation](../README.md#install-the-python-tool) that will remain available to
root and systemd. Invoke `apply` using its absolute entry, as root or through explicit sudo.
The rendered ExecStart is equivalent to:

```text
ExecStart=:"/absolute/tool/environment/bin/python" "-m" "dnsleaf" "sync-once" "--workspace" "/absolute/workspace" "--apply"
```

It uses `sys.executable` from the installing process, made absolute without resolving symlinks.
This preserves virtualenv semantics even when `bin/python` points to a base interpreter.
It never discovers a different CLI using PATH. Each argument is quoted for systemd; backslashes,
quotes, control characters, and percent specifiers are escaped. The `:` prefix disables environment
expansion for all arguments, including dollar signs in the executable path. No shell is involved.
See the upstream [systemd command syntax](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html#Command%20lines)
and [quoting rules](https://www.freedesktop.org/software/systemd/man/latest/systemd.syntax.html#Quoting).

After upgrading or moving the tool environment, invoke `apply --no-run-sync` again with the new
absolute entry. Do not delete its Python environment while timers still use it.

## Status and logs

```bash
/absolute/path/to/dnsleaf status --workspace /etc/dnsleaf/example-zone
systemctl status dnsleaf-example-zone.timer
journalctl -u dnsleaf-example-zone.service
```

A successful oneshot normally becomes inactive after finishing. Workspace log output uses
`runtime/logs/dnsleaf.log`, pointing to the current daily file. `status` reports unit load and active
states, artifact presence, log paths, managed records, and the last local installation.
`doctor` checks configuration, paths, command availability, and local permissions without DNS writes.

## Local uninstall

`uninstall` requires root and performs these operations in order:

1. Stop the timer, then stop the service, then disable the timer.
2. Remove this workspace's unit files and reload systemd.
3. Reset retained failed status as best-effort cleanup.
4. Remove generated `rendered/` and `runtime/` data.

A stop or disable error aborts before deleting local artifacts unless systemd confirms the target
is already absent and inactive. Missing systemctl and failed daemon reload are errors, not success.
`reset-failed` failures are warnings after the essential cleanup.

Normal uninstall keeps `workspace.yaml`, `entries.yaml`, credentials, and `state/`.
`uninstall --purge` explicitly removes the workspace after service cleanup, with conservative guards
against deleting broad paths or following generated-directory symlinks outside the workspace.
Neither operation contacts Cloudflare or deletes remote DNS.
