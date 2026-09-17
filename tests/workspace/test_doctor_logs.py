from pathlib import Path

import pytest

from dnsleaf.workspace.service import WorkspaceService, _path_write_target_available
from dnsleaf.workspace.storage import dump_yaml_data
from tests.fakes import FakeSystemdManager


@pytest.mark.parametrize("kind", ["file", "symlink", "missing", "directory", "dangling-parent"])
def test_log_path_types(tmp_path: Path, monkeypatch, kind):
    path = tmp_path / "dnsleaf.log"
    if kind == "file":
        path.write_text("log")
    elif kind == "symlink":
        target = tmp_path / "dnsleaf-2026-09-17.log"
        target.write_text("log")
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    elif kind == "dangling-parent":
        path.symlink_to(tmp_path / "missing-parent" / "target")
    monkeypatch.setattr("dnsleaf.workspace.service.os.access", lambda path, mode: True)
    assert _path_write_target_available(path) == (kind in {"file", "symlink", "missing"})


@pytest.mark.parametrize("existing", [False, True])
def test_permissions_mocked_without_root_chmod_assumptions(tmp_path: Path, monkeypatch, existing):
    path = tmp_path / "dnsleaf.log"
    if existing:
        path.write_text("log")
    monkeypatch.setattr("dnsleaf.workspace.service.os.access", lambda path, mode: False)
    assert not _path_write_target_available(path)


def test_disabled_logging_checks_no_fallback_and_doctor_is_read_only(
    workspace_dir, tmp_path, monkeypatch
):
    dump_yaml_data(workspace_dir / "workspace.yaml", {"dnsleaf_logging": {"file_path": None}})
    before = {
        p.relative_to(workspace_dir): p.read_bytes()
        for p in workspace_dir.rglob("*")
        if p.is_file()
    }

    def unexpected(path):
        raise AssertionError("disabled logging must not inspect an unused log target")

    monkeypatch.setattr("dnsleaf.workspace.service._path_write_target_available", unexpected)
    service = WorkspaceService(systemd_manager=FakeSystemdManager(tmp_path / "units"))
    report = service.doctor_workspace(workspace_dir)
    check = next(c for c in report.checks if c.name == "runtime_log_target")
    assert check.status == "ok" and check.message == "file logging is disabled"
    assert service.status_workspace(workspace_dir).runtime_log_file is None
    assert before == {
        p.relative_to(workspace_dir): p.read_bytes()
        for p in workspace_dir.rglob("*")
        if p.is_file()
    }
