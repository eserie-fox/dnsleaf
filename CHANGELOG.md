# Changelog

## 1.0.0 - 2026-04-01

`arbor-ddns` is ready for internal 1.0.0 use on a local machine.

- finalized the workspace-centric configuration model around `workspace.yaml`
- clarified the outside-workspace defaults layer as an internal fallback, not an operator-facing app config
- unified arbor-ddns logging schema across workspace and outside-workspace execution
- cleaned up shared path modeling so discovery fallbacks and workspace-only systemd paths have clearer ownership
- moved scaffold default construction into typed model/config helpers instead of leaving it spread across storage
- removed obsolete compatibility residue and aligned tests with the current CLI output surface
- updated version metadata, release notes, and local build/install guidance for internal release preparation
