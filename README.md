# dnsleaf

[![CI](https://github.com/eserie-fox/dnsleaf/actions/workflows/ci.yml/badge.svg)](https://github.com/eserie-fox/dnsleaf/actions/workflows/ci.yml)

Workspace-driven Cloudflare DDNS for Linux, primarily Proxmox VE hosts. Requires Python 3.11+.
Each entry publishes IPv4, IPv6, or both from a PVE LXC guest, a PVE VM guest agent,
the local host, or explicit static addresses. A oneshot sync and a system-level systemd timer
handle periodic updates. Cloudflare is the only supported provider.

**1.1.0 is pending release.** The public PyPI installation commands below apply after publication.
Before publication, install the reviewed wheel with the same `uv tool install` command.

## Install the Python tool

Use [uv](https://docs.astral.sh/uv/guides/tools/) for a persistent, isolated installation.
For PVE system services, run these commands in a root shell with uv available:

```bash
uv tool install --python 3.11 dnsleaf
DNSLEAF="$(uv tool dir --bin)/dnsleaf"
"$DNSLEAF" --version
"$DNSLEAF" --help
```

For pre-release review, replace `dnsleaf` in the install command with the absolute path to
`dnsleaf-1.1.0-py3-none-any.whl`. Installing the package creates a CLI; it does not install a timer
or synchronize DNS. Keep this tool environment and its Python interpreter installed for the timer.
The module entrypoint is `python -m dnsleaf` when that Python environment contains the package.

Unprivileged users can initialize and validate writable workspaces, and sync local/static entries
when credentials and state are accessible. PVE guest discovery requires host privileges.
`apply` and `uninstall` require root. From a non-root shell, use explicit sudo with the **absolute**
installed entry, for example `sudo /absolute/path/to/dnsleaf apply --workspace /etc/dnsleaf/example-zone`.
The tool never elevates itself.

## Create and configure a workspace

In the same root shell:

```bash
"$DNSLEAF" init /etc/dnsleaf/example-zone
chmod 700 /etc/dnsleaf/example-zone
install -m 600 /dev/null /etc/dnsleaf/example-zone/secrets/cloudflare_api_token.txt
```

Put your Cloudflare API token in that file using your editor. Restrict it to the intended zone
and grant the DNS permissions needed for record reads and edits; zone lookup by name also needs
zone read access. Never put the token in YAML, commands, Git, or shared reports.

Edit `/etc/dnsleaf/example-zone/workspace.yaml`: set `zone_name`, optionally `zone_id`, and keep
`api_token_file` pointing to the token file. Its relative path is based on the workspace directory.
The generated YAML contains the packaged defaults; partial overrides are also supported.
See [configuration](docs/configuration.md) for schema 4 and all settings.

Add entries with the CLI, or edit `entries.yaml` (schema 2):

```bash
"$DNSLEAF" entry add lxc --workspace /etc/dnsleaf/example-zone \
  --id 101 --fqdn web.example.com --name web --family both
"$DNSLEAF" entry add vm --workspace /etc/dnsleaf/example-zone \
  --id 201 --fqdn vm.example.com --name vm --family ipv6
"$DNSLEAF" entry add local --workspace /etc/dnsleaf/example-zone \
  --fqdn host.example.com --name host --family both
"$DNSLEAF" entry add static --workspace /etc/dnsleaf/example-zone \
  --fqdn edge.example.com --name edge --family both \
  --ipv4 192.0.2.10 --ipv6 2001:db8::10
```

These names, guest IDs, and static documentation addresses are placeholders: use your own values.
LXC discovery uses `pct exec`; VM discovery needs a working QEMU guest agent; local discovery uses
`ip`. See [discovery](docs/discovery.md) and [entry management](docs/entry_management.md).

## Validate, plan, and synchronize

```bash
"$DNSLEAF" validate --workspace /etc/dnsleaf/example-zone
"$DNSLEAF" plan --workspace /etc/dnsleaf/example-zone
"$DNSLEAF" sync-once --workspace /etc/dnsleaf/example-zone --apply
```

`validate` checks local configuration and token readability without API calls. `plan` and
`sync-once` without `--apply` read Cloudflare state and discover addresses, but never change DNS.
`sync-once --apply` performs one immediate sync. These commands may write workspace logs.

IPv4 and IPv6 are handled independently. Missing or ambiguous addresses are skipped without
publishing guesses or deleting existing records. `default_ttl: auto` uses Cloudflare automatic TTL;
`default_proxied: null` preserves existing proxy settings. Entry overrides may set `true` or `false`.
Prune is off by default; explicit `--prune-managed` only removes stale records tracked by this
workspace. Unmanaged zone records are preserved. See [DNS sync](docs/dns_sync.md).

## Install the timer

```bash
"$DNSLEAF" apply --workspace /etc/dnsleaf/example-zone --no-run-sync
"$DNSLEAF" status --workspace /etc/dnsleaf/example-zone
systemctl status dnsleaf-example-zone.timer
journalctl -u dnsleaf-example-zone.service
```

`apply` validates and renders the workspace, installs system units, then enables and restarts the
timer. `--no-run-sync` skips the command's immediate sync; the enabled timer will still run on its
schedule. `render` only writes local generated artifacts. The service uses the absolute Python
from the environment that ran `apply`, followed by `-m dnsleaf`, so its entry does not depend on
an interactive shell's PATH or a development checkout. See [systemd](docs/systemd.md).

Workspace files are separated by purpose:

| Location | Purpose |
| --- | --- |
| `workspace.yaml`, `entries.yaml` | User configuration |
| `secrets/` | Local token file |
| `rendered/` | Effective JSON and generated unit files |
| `runtime/logs/dnsleaf.log` | Symlink to the current daily log |
| `state/` | Last installation and explicitly managed DNS records |

## Upgrade and uninstall

Upgrade the persistent tool, then refresh units using the updated entry:

```bash
uv tool upgrade dnsleaf
DNSLEAF="$(uv tool dir --bin)/dnsleaf"
"$DNSLEAF" apply --workspace /etc/dnsleaf/example-zone --no-run-sync
```

Remove the local service installation before uninstalling the Python tool:

```bash
"$DNSLEAF" uninstall --workspace /etc/dnsleaf/example-zone
uv tool uninstall dnsleaf
```

Repeat local service removal for every installed workspace before removing the tool environment.
Normal `uninstall` retains configuration, credentials, and state. To explicitly delete a workspace,
use `uninstall --purge` while the tool is still installed. Neither form deletes remote DNS records.
A stop/disable failure aborts cleanup and returns failure. Earlier private deployments must be
uninstalled separately and configured afresh; no in-place compatibility migration is provided.

## Development and release

```bash
make sync
make check
make build
```

See [development](docs/development.md), [architecture](docs/architecture.md),
[release preparation](docs/release.md), [1.1.0 notes](docs/release-notes/1.1.0.md), and
[CHANGELOG](CHANGELOG.md). Author: eserie-fox. License: [MIT](LICENSE).
