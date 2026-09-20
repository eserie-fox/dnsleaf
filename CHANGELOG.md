# Changelog

## 1.4.0 — pending release

- Breaking: require explicit workspace schema 5 and entries schema 3; remove the windows-dhcpv6 preset.
- Separate `require-dhcpv6` selection from `windows-powershell` evidence permission, with independent
  nullable overrides and one exact VM-ID source-default layer. Report effective values and origins.
- Normalize correlated evidence before pure, OS-independent strict selection; retain the fixed probe,
  conservative inventory checks, per-run acquisition reuse and DNS/prune safeguards.
- Preserve inheritance on entry edits, add explicit override clearing, and validate effective settings
  before atomic replacement. Clarify discovery versus enrollment versus publication.
- Preserve operational state, credentials and unit names. Package/config replacement must be
  coordinated by the operator; no runtime conversion or compatibility loader is provided.

See [1.4.0 notes](docs/release-notes/1.4.0.md).


## 1.3.0 — pending release

- Added opt-in `windows-dhcpv6` IPv6 selection for VM ipv6/both entries and `discover vm`.
- Kept the default policy and its Guest commands unchanged. Strict selection requires Windows
  DHCP origins, Preferred state and SkipAsSource=false corroborated by QGA address/MAC identity.
- Added a fixed packaged PowerShell 5.1 read-only metadata probe through bounded synchronous
  `qm guest exec`, with explicit completion, exit, truncation, schema and encoding validation.
- Refused incomplete/conflicting snapshots without heuristic fallback; exposed supplementary
  errors independently of raw discovery and IPv4, preserving configured DNS targets.
- Shared one raw and at most one supplementary snapshot per VM per run, including failed results.
- Added synthetic protocol, selection, CLI, caching and fake-DNS safety regressions. No configuration,
  state or systemd migration is required; live Windows/PVE acceptance and publication are separate.

See [1.3.0 notes](docs/release-notes/1.3.0.md).

## 1.2.0 — pending release

- Added explicit CLI / DNSLEAF_WORKSPACE / children-before-base automatic workspace selection.
- Required only workspace.yaml and entries.yaml for location; partial candidates warn and continue,
  complete candidates validate strictly without fallback, and inspection failures remain errors.
- Reused one configuration snapshot per command and one raw discovery result per source per run.
- Covered Windows Guests with synthetic standard QGA fixtures through the existing VM backend.
- Added a shared package-default 30-second discovery timeout and unique enabled DNS-target validation.
- Separated CLI output, report DTOs and deterministic managed-state reconciliation; corrected doctor
  log-path diagnostics and discovery exit handling while retaining prune, proxy and systemd safety.
- Kept workspace/entries/state schemas unchanged; existing dnsleaf deployments need no move or reset.

See [1.2.0 notes](docs/release-notes/1.2.0.md). Publication and live-PVE acceptance remain separate.

## 1.1.0 — pending release

- Unified the project as `dnsleaf` (repository, PyPI distribution, package, CLI, and module entry).
- Prepared public PyPI metadata, MIT licensing, setuptools resources, shared CI/build callers,
  OIDC publishing jobs, and CI-aligned development commands.
- Workspace schema 4 uses `dnsleaf_logging` and defaults-plus-overrides validation; entries remain
  schema 2. Runtime paths resolve separately and unknown fields are rejected.
- Removed automatic sudo re-execution. Systemd binds the installing Python environment and escapes
  arguments correctly. Uninstall stops the timer first and reports essential cleanup failures.
- Fixed normal sync to reject multiple remote records of the same name/type without deleting extras.
- Retained managed-only prune, per-family safety, proxy preservation, and thin package interfaces.
- Fixed prune safety for re-enabled or renamed entries: configured DNS targets remain protected
  regardless of discovery results, and ownership is reconciled without conflicting stale aliases.
- Private installations require a fresh workspace after separate uninstall, without compatibility migration.

See [1.1.0 notes](docs/release-notes/1.1.0.md) and [release gates](docs/release.md).

## Pre-rename internal history

The following 1.0.x entries describe the private `arbor-ddns` project. They are historical internal
release-preparation records, not claims of earlier public `dnsleaf` releases. Commands and paths
in the archived notes are not current installation instructions.

## 1.0.3 - 2026-04-02

`arbor-ddns` 1.0.3 is ready for internal patch-release use on a local machine.

- fixed `entry update` so operators can explicitly clear an entry-level `proxied` override and return to inheriting the workspace default
- aligned `entry` proxied flags around explicit `--proxied/--no-proxied` behavior instead of leaving update as a one-way flag
- updated tests, operator docs, release notes, and version metadata for the 1.0.3 release-prep pass

## 1.0.2 - 2026-04-01

`arbor-ddns` 1.0.2 is ready for internal patch-release use on a local machine.

- added `local` as a first-class dynamic source kind for host-local IP discovery
- fixed workspace daily log naming so the stable `arbor-ddns.log` symlink path does not accumulate repeated date suffixes
- aligned help text, documentation, release notes, tests, and version metadata for the 1.0.2 release-prep pass

## 1.0.1 - 2026-04-01

`arbor-ddns` 1.0.1 is ready for internal patch-release use on a local machine.

- improved `--sudo` re-exec behavior for non-root operators working from `.venv` or similar Python-managed installs
- preserved explicit negative flag semantics during sudo re-exec and tightened argument reconstruction fail-fast boundaries
- made QGA discovery parsing more tolerant of partial bad interface data without masking malformed top-level payloads
- unified Python module fallback usage around `python -m arbor_ddns` for CLI and systemd execution paths
- updated operator documentation, release notes, and tests to match the finalized 1.0.1 behavior

## 1.0.0 - 2026-04-01

`arbor-ddns` is ready for internal 1.0.0 use on a local machine.

- finalized the workspace-centric configuration model around `workspace.yaml`
- clarified the outside-workspace defaults layer as an internal fallback, not an operator-facing app config
- unified arbor-ddns logging schema across workspace and outside-workspace execution
- cleaned up shared path modeling so discovery fallbacks and workspace-only systemd paths have clearer ownership
- moved scaffold default construction into typed model/config helpers instead of leaving it spread across storage
- removed obsolete compatibility residue and aligned tests with the current CLI output surface
- updated version metadata, release notes, and local build/install guidance for internal release preparation
