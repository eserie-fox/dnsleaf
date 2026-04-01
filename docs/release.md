# Internal Release Workflow

This document is for local builds and installs on your own machines. It does not describe PyPI publishing.

## Prerequisites

- Python 3.11 or newer
- `uv` for creating and syncing the local virtual environment

Install development tooling so `build`, `pytest`, `ruff`, and `mypy` are available:

```bash
uv sync --extra dev --python 3.11
```

## Build artifacts

Create a source distribution and wheel from the current checkout:

```bash
.venv/bin/python -m build
```

Expected outputs:

- `dist/arbor_ddns-1.0.0.tar.gz`
- `dist/arbor_ddns-1.0.0-py3-none-any.whl`

## Local install

Install the built wheel into the target environment:

```bash
pip install dist/arbor_ddns-1.0.0-py3-none-any.whl
```

If you are reinstalling over an older local build, use your normal `pip install --force-reinstall ...` workflow.

## Verify the installed CLI

Check the version first:

```bash
arbor-ddns --version
```

Expected output:

```text
1.0.0
```

## Minimal smoke test

Initialize a workspace and verify the installed CLI can operate on it:

```bash
arbor-ddns init ./release-smoke
arbor-ddns entry list --workspace ./release-smoke
```

To validate a real workspace end-to-end:

1. put a Cloudflare token in `./release-smoke/secrets/cloudflare_api_token.txt`
2. add at least one entry with `arbor-ddns entry add ...`
3. run `arbor-ddns validate --workspace ./release-smoke`
4. run `arbor-ddns provider verify --workspace ./release-smoke`
5. optionally run `arbor-ddns render`, `plan`, `sync-once --apply`, or `apply`

## Release notes

- [1.0.0 release notes](release-notes/1.0.0.md)
- [Changelog](../CHANGELOG.md)
