# Release preparation

Version **1.1.0 is pending release**. These instructions prepare a public package; they do not
assert that PyPI projects, publishers, GitHub environments, or branch protection already exist.

## Identity and build

Distribution, import package, executable, and GitHub repository are `dnsleaf`.
Repository owner and author are `eserie-fox`; license is MIT; Python minimum is 3.11.
The only version definition is `src/dnsleaf/version.py`, read dynamically by setuptools and the CLI.

```bash
uv sync --python 3.11 --extra dev
make check
UV_PROJECT_ENVIRONMENT=/tmp/dnsleaf-py313 uv sync --python 3.13 --extra dev
UV_PROJECT_ENVIRONMENT=/tmp/dnsleaf-py313 uv run pytest
uv build --python 3.11
uv run twine check dist/*
```

Use a clean output directory for release artifacts. Confirm wheel/sdist metadata, MIT license,
entrypoint, author, URLs, defaults and templates. Inspect every member for accidental workspaces,
credentials, logs, cache files, and stale packages. In a fresh environment outside the checkout,
install the wheel without editable mode or a source PYTHONPATH. Verify `dnsleaf` and
`python -m dnsleaf` help/version, initialize a workspace, supply an explicit test-only token file,
then validate and render without network access. Rebuild a wheel from the unpacked sdist and
repeat installation checks. Package metadata, `version.py`, and CLI version must agree.

## Workflows

[ci.yml](../.github/workflows/ci.yml) calls
[python-ci.yml@main](https://github.com/eserie-fox/github-workflows/blob/main/.github/workflows/python-ci.yml)
on ordinary PRs and pushes to main. Inputs request Ubuntu Python 3.11/3.13 and `typecheck: true`.
Stable required checks are `ci / format-lint` and `ci / tests`.

[publish.yml](../.github/workflows/publish.yml) calls
[python-build.yml@main](https://github.com/eserie-fox/github-workflows/blob/main/.github/workflows/python-build.yml)
once, then downloads `python-package-distributions` for publication. Manual `workflow_dispatch`
publishes to TestPyPI. A newly created `v*` tag publishes to PyPI. Tag deletion, ordinary PRs,
and main pushes do not publish. The local publishing jobs use OIDC with only `id-token: write`.
The build job has `contents: read`. Shared implementations remain in the shared repository.

## Account settings to complete manually

Create the project or a pending Trusted Publisher separately on both indexes:

| Setting | TestPyPI | PyPI |
| --- | --- | --- |
| Project | `dnsleaf` | `dnsleaf` |
| GitHub owner | `eserie-fox` | `eserie-fox` |
| Repository | `dnsleaf` | `dnsleaf` |
| Workflow filename | `publish.yml` | `publish.yml` |
| Environment | `testpypi` | `pypi` |
| Project URL | https://test.pypi.org/project/dnsleaf/ | https://pypi.org/project/dnsleaf/ |

Create matching GitHub environments and choose their review protections. Configure the two stable
CI checks above as required checks after their first successful run. Verify the reusable workflow's
live `main` supports the declared inputs. No long-lived publishing secret is needed.

## Public release gates

Before changing visibility or publishing, review current tracked/untracked deliverables, package
contents, and **all locally available Git refs/history** for credentials and private deployment data.
Only report locations and types of findings, never secret values. Lightweight scans cannot certify
absence of secrets; inspect findings and also review refs not present locally. Do not rewrite or
force-push history automatically. Any sensitive historical data requires owner review before exposure.

Run PVE acceptance separately on an authorized test host: LXC/VM/local discovery, real zone planning,
then intentional writes, timer execution, permission handling, and uninstall failure recovery.
Local unit tests with fakes do not establish PVE or live Cloudflare acceptance.

Old private installations require uninstalling the old tool separately and creating a new workspace
and token reference. There is no package alias, command alias, config conversion, state migration,
or in-place upgrade path. The 1.0.x notes record pre-rename internal work, not public dnsleaf releases.

After review and account setup, manually run the TestPyPI workflow. Verify its published artifacts
before creating the intended PyPI tag. Neither a local build nor this document implies publication.
