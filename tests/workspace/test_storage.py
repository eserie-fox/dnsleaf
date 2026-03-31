from __future__ import annotations

import json
from pathlib import Path

import pytest

from arbor_ddns.workspace.service import WorkspaceService
from arbor_ddns.workspace.storage import WorkspaceInitError


def test_init_creates_expected_workspace_tree(tmp_path: Path) -> None:
    workspace = tmp_path / "lab"

    created = WorkspaceService().init_workspace(workspace)

    assert created == workspace.resolve()
    assert (workspace / "workspace.yaml").exists()
    assert (workspace / "entries.yaml").exists()
    assert (workspace / "secrets" / "README.txt").exists()
    assert (workspace / "rendered" / "systemd").is_dir()
    assert (workspace / "state" / "managed-records.json").exists()


def test_init_allows_existing_empty_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "lab"
    workspace.mkdir()

    WorkspaceService().init_workspace(workspace)

    assert (workspace / "workspace.yaml").exists()


def test_init_rejects_existing_non_empty_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "lab"
    workspace.mkdir()
    (workspace / "note.txt").write_text("x", encoding="utf-8")

    with pytest.raises(WorkspaceInitError):
        WorkspaceService().init_workspace(workspace)


def test_validate_resolves_relative_token_file(workspace_dir: Path) -> None:
    report = WorkspaceService().validate_workspace(workspace_dir)

    assert report.workspace_name == "lab"
    assert report.token_file.endswith("secrets/cloudflare_api_token.txt")


def test_validate_rejects_reserved_a_record_type(workspace_dir: Path) -> None:
    (workspace_dir / "entries.yaml").write_text(
        (
            "config_version: 1\n"
            "entries:\n"
            "  - name: web\n"
            "    source_kind: lxc\n"
            "    source_id: 101\n"
            "    fqdn: host.example.com\n"
            "    record_type: A\n"
            "    selection_policy: default\n"
            "    enabled: true\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reserved"):
        WorkspaceService().validate_workspace(workspace_dir)


def test_render_generates_effective_workspace_and_systemd_artifacts(workspace_dir: Path) -> None:
    (workspace_dir / "entries.yaml").write_text(
        (
            "config_version: 1\n"
            "entries:\n"
            "  - name: web\n"
            "    source_kind: lxc\n"
            "    source_id: 101\n"
            "    fqdn: host.example.com\n"
            "    record_type: AAAA\n"
            "    selection_policy: default\n"
            "    enabled: true\n"
        ),
        encoding="utf-8",
    )

    report = WorkspaceService().render_workspace(workspace_dir)

    effective = json.loads(Path(report.effective_workspace_file).read_text(encoding="utf-8"))
    desired = json.loads(Path(report.desired_records_file).read_text(encoding="utf-8"))
    service_unit = Path(report.service_unit_file).read_text(encoding="utf-8")
    timer_unit = Path(report.timer_unit_file).read_text(encoding="utf-8")

    assert effective["workspace_name"] == "lab"
    assert "secret-token" not in json.dumps(effective)
    assert desired["records"][0]["entry_name"] == "web"
    assert "ExecStart=" in service_unit
    assert "OnUnitActiveSec=" in timer_unit
