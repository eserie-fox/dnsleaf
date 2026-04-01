# Changelog

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
