from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from arbor_ddns.workspace.models import EntriesFile, WorkspaceConfig
from arbor_ddns.workspace.service import WorkspaceService
from arbor_ddns.workspace.storage import WorkspaceInitError, WorkspaceStorage


def test_init_creates_expected_workspace_tree(tmp_path: Path) -> None:
    workspace = tmp_path / "lab"

    created = WorkspaceService().init_workspace(workspace)

    assert created == workspace.resolve()
    assert (workspace / "workspace.yaml").exists()
    assert (workspace / "entries.yaml").exists()
    assert (workspace / "secrets" / "README.txt").exists()
    assert (workspace / "rendered" / "systemd").is_dir()
    assert (workspace / "runtime" / "logs").is_dir()
    assert (workspace / "runtime" / "run").is_dir()
    assert (workspace / "state" / "managed-records.json").exists()

    workspace_payload = yaml.safe_load((workspace / "workspace.yaml").read_text(encoding="utf-8"))
    assert workspace_payload["config_version"] == 3
    assert workspace_payload["default_ttl"] == "auto"
    assert workspace_payload["default_proxied"] is None
    assert workspace_payload["paths"]["systemctl_bin"] == "systemctl"


def test_workspace_scaffold_defaults_build_typed_model() -> None:
    workspace_config = WorkspaceConfig.scaffold_defaults("lab")

    assert workspace_config.workspace_name == "lab"
    assert workspace_config.default_ttl == "auto"
    assert workspace_config.default_proxied is None
    assert workspace_config.paths.pct_bin == "pct"
    assert workspace_config.paths.systemctl_bin == "systemctl"
    assert workspace_config.arbor_ddns_logging.file_path == "runtime/logs/arbor-ddns.log"
    assert workspace_config.arbor_ddns_logging.stream == "none"


def test_entries_scaffold_defaults_build_typed_model() -> None:
    entries = EntriesFile.scaffold_defaults()

    assert entries.config_version == 2
    assert entries.entries == []


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


def test_validate_rejects_old_workspace_schema_version(workspace_dir: Path) -> None:
    payload = yaml.safe_load((workspace_dir / "workspace.yaml").read_text(encoding="utf-8"))
    payload["config_version"] = 2
    (workspace_dir / "workspace.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="config_version must be exactly 3"):
        WorkspaceService().validate_workspace(workspace_dir)


def test_validate_resolves_relative_systemd_unit_dir(workspace_dir: Path) -> None:
    payload = yaml.safe_load((workspace_dir / "workspace.yaml").read_text(encoding="utf-8"))
    payload["paths"]["systemd_unit_dir"] = "local/systemd"
    (workspace_dir / "workspace.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    loaded = WorkspaceStorage().validate(workspace_dir)

    assert loaded.resolved_workspace.paths.resolved_systemd_unit_dir() == (
        workspace_dir / "local" / "systemd"
    ).resolve()


def test_validate_rejects_old_record_type_entry_schema(workspace_dir: Path) -> None:
    (workspace_dir / "entries.yaml").write_text(
        (
            "config_version: 2\n"
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

    with pytest.raises(ValueError, match="family|record_type|Field required|Extra inputs"):
        WorkspaceService().validate_workspace(workspace_dir)


def test_validate_rejects_static_entry_without_matching_values(workspace_dir: Path) -> None:
    (workspace_dir / "entries.yaml").write_text(
        (
            "config_version: 2\n"
            "entries:\n"
            "  - name: edge\n"
            "    source_kind: static\n"
            "    fqdn: edge.example.com\n"
            "    family: both\n"
            "    static_ipv6: 2408:8266:5003:506a::88\n"
            "    enabled: true\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="static_ipv4 is required"):
        WorkspaceService().validate_workspace(workspace_dir)


def test_render_generates_effective_workspace_and_systemd_artifacts(workspace_dir: Path) -> None:
    (workspace_dir / "entries.yaml").write_text(
        (
            "config_version: 2\n"
            "entries:\n"
            "  - name: web\n"
            "    source_kind: lxc\n"
            "    source_id: 101\n"
            "    fqdn: host.example.com\n"
            "    family: both\n"
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
    assert len(desired["records"]) == 2
    assert {record["record_type"] for record in desired["records"]} == {"A", "AAAA"}
    assert desired["records"][0]["entry_name"] == "web"
    assert all(record["proxied"] is None for record in desired["records"])
    assert "ExecStart=" in service_unit
    assert "OnUnitActiveSec=" in timer_unit
