from __future__ import annotations

from arbor_ddns.systemd import SystemdManager
from arbor_ddns.workspace.storage import WorkspaceStorage


def test_render_service_unit_falls_back_to_python_module_entrypoint(
    tmp_path,
    monkeypatch,
) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    loaded = WorkspaceStorage().load(workspace_dir)

    monkeypatch.setattr("arbor_ddns.systemd.shutil.which", lambda command: None)
    monkeypatch.setattr("arbor_ddns.systemd.sys.executable", "/opt/venv/bin/python")

    unit_text = SystemdManager().render_service_unit(loaded.resolved_workspace)

    assert (
        "ExecStart=/opt/venv/bin/python -m arbor_ddns sync-once --workspace "
        f"{workspace_dir.resolve()} --apply"
    ) in unit_text
    assert "arbor_ddns.cli" not in unit_text
