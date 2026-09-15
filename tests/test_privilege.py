from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dnsleaf import cli
from dnsleaf.util.privilege import require_root
from dnsleaf.workspace.service import WorkspaceService
from dnsleaf.workspace.storage import WorkspaceInitError


def test_require_root_does_not_reexecute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dnsleaf.util.privilege.os.geteuid", lambda: 1000)
    with pytest.raises(PermissionError):
        require_root("apply")
    monkeypatch.setattr("dnsleaf.util.privilege.os.geteuid", lambda: 0)
    require_root("apply")


@pytest.mark.parametrize("args", [["--help"], ["--version"]])
def test_public_cli_does_not_require_root(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    monkeypatch.setattr("dnsleaf.util.privilege.os.geteuid", lambda: 1000)
    assert CliRunner().invoke(cli.app, args).exit_code == 0


def test_nonroot_can_initialize_and_validate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("dnsleaf.util.privilege.os.geteuid", lambda: 1000)
    runner = CliRunner()
    workspace = tmp_path / "demo"
    assert runner.invoke(cli.app, ["init", str(workspace)]).exit_code == 0
    (workspace / "secrets/cloudflare_api_token.txt").write_text("TEST_ONLY_TOKEN\n")
    assert runner.invoke(cli.app, ["validate", "-w", str(workspace)]).exit_code == 0


def test_failed_init_does_not_overwrite_existing_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    existing = workspace / "workspace.yaml"
    existing.write_text("keep me\n")
    with pytest.raises(WorkspaceInitError):
        WorkspaceService().init_workspace(workspace)
    assert existing.read_text() == "keep me\n"
