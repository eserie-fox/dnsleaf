# Development

This repository intentionally stays narrow and predictable.

## Structural constraints

- All `__init__.py` files stay thin package markers.
- Every `__init__.py` must set `__all__: list[str] = []`.
- Package-level re-exports are not allowed; imports must target the defining module directly.
- The root CLI is only a command entry surface.
- `sync/runner.py` stays orchestration-focused, with raw snapshots scoped to one run.
- `workspace/locator.py` owns location only: sorted children before each base, first complete match.
- `commands/output.py` owns presentation; normal service operations receive `LoadedWorkspace`.
- `workspace/reports.py` owns operation DTOs without importing services/runners.
- `workspace/state.py` owns reconciliation with an explicit timestamp and immutable previous input.
- `dns/identity.py` shares target normalization between configuration validation and state.
- Discovery backends only return candidate addresses.
- Address selection happens in discovery/selector code, not in DNS providers.
- DNS providers never guess which IP should be published.
- Workspace source files are the main user-maintained state.
- Rendered artifacts and state files are generated outputs.
- One entry may expand to two concrete record flows when `family=both`.
- Static entries bypass discovery and selection.

## Configuration constraints

- Outside-workspace defaults follow the formal runtime config pattern.
- Outside-workspace defaults live under the `dnsleaf.config` package.
- Formal defaults live in `src/dnsleaf/config_defaults/`; scaffold text and layout live in `src/dnsleaf/templates/`.
- Loading order is fixed: defaults -> override -> deep merge -> validate.
- Runtime-only resolution is explicit and separate from raw config loading.
- Operator-facing execution config belongs in `workspace.yaml`, not in a root CLI config file.
- Shared semantics should reuse shared sub-models instead of duplicating near-identical config schemas.
- Secrets are not embedded in source config files.
- Cloudflare API tokens are read from `api_token_file`.
- Token contents must never be printed in logs or reports.
- Workspace logging is configured from `workspace.yaml` via `dnsleaf_logging`.

## Execution constraints

- Current execution is serial.
- Discovery command execution is centralized in `util/process.py`.
- systemd integration is system-level only in this round.
- Command entrypoints own workspace logging context; services use normal stdlib loggers.
- Normal apply does not delete remote DNS records.
- Prune only targets records previously tracked by the workspace state file.
- If a tracked record cannot be deleted safely by `record_id`, it is skipped instead of guessed.
- Default uninstall is local-only cleanup and never deletes remote DNS records.
- Default uninstall keeps `state/` so managed-record ownership history survives reinstall.

## Scope constraints

- Provider scope is Cloudflare only.
- Dynamic discovery currently supports both IPv4 and IPv6.
- Static entries support explicit IPv4, IPv6, and dual-stack values.
- Keep scope to Linux/PVE, Cloudflare, and oneshot sync with system-level timers.

## Environment and checks

Install uv, then run `make sync` and `make check`. The equivalent CI commands are:

```bash
uv sync --python 3.11 --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

Repeat pytest with Python 3.13 in a separate environment:

```bash
UV_PROJECT_ENVIRONMENT=/tmp/dnsleaf-py313 uv sync --python 3.13 --extra dev
UV_PROJECT_ENVIRONMENT=/tmp/dnsleaf-py313 uv run pytest
```

The shared workflows accept unlocked dependency resolution. `uv.lock` is local and ignored;
this library/tool repository does not introduce a committed lockfile policy.
`make format` applies formatting; `make build` runs `uv build --python 3.11` and `twine check dist/*`.

Production code remains strictly typed. The scoped `tests.*` override permits partially annotated
pytest fixtures and fake helpers while retaining type checking inside annotated functions.
Tests use fake command runners, HTTP transports, and temporary directories. The autouse guard
blocks unintended subprocess execution and network connections. Never run real systemctl, pct,
qm, or Cloudflare writes from tests. Synthetic globally scoped addresses in selector fixtures
exercise address classification; they do not identify deployed guests and are never contacted.

## Packaging and review

Setuptools discovers only `dnsleaf` packages under `src/`. Runtime resources are explicit package data.
Version is defined only in `dnsleaf.version.__version__`; all `__init__.py` files retain
`__all__: list[str] = []`. Do not add package-level re-exports.

Keep `CHANGELOG.md` and `docs/release-notes/<version>.md` aligned. Before review, run `git diff --check`
and inspect the wheel/sdist and a fresh non-editable installation outside the checkout, including
an sdist rebuild. See [release](release.md) for account settings and publication gates.

`MANIFEST.in` only selects development docs and the complete test tree for the sdist; it does not
configure another build system or add files to the installed wheel.

Workspace command tests must inject bounded search bases for no-match cases; never scan a developer's
real ancestors or home. Test the base-generation order separately. Partial warnings use stderr outside
workspace logging. Do not add discovery to storage APIs that already receive a root. Keep diagnostics
for status/doctor outside any logging context that first requires a successful source load.

Discovery limits are shared formal defaults in `config_defaults/discovery.json`, merged into workspace
and outside-workspace configurations. They apply only to address-discovery commands. New process
fakes must accept `timeout` explicitly; do not guess old signatures by catching TypeError.

Windows Guest tests are synthetic standard QGA fixtures. No Windows host runner, live-PVE CI, guest
OS probing or Guest-side updater is needed. Keep the stable `ci / format-lint` and `ci / tests` checks.
