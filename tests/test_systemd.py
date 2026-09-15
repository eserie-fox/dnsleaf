from __future__ import annotations

from pathlib import Path

import pytest

from dnsleaf.systemd import SystemdManager, _systemd_escape_arg
from dnsleaf.workspace.models import WorkspaceConfig
from dnsleaf.workspace.storage import WorkspaceStorage
from tests.conftest import scaffold_workspace


def test_service_binds_installer_python_even_with_another_cli_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = scaffold_workspace(tmp_path)
    loaded = WorkspaceStorage().load(workspace)
    python = tmp_path / "tool env/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to("/usr/bin/python3")
    monkeypatch.setattr("dnsleaf.systemd.sys.executable", str(python))
    monkeypatch.setattr("dnsleaf.systemd.shutil.which", lambda command: "/wrong/dnsleaf")
    manager = SystemdManager()
    assert manager._exec_start_args(workspace) == [
        str(python),
        "-m",
        "dnsleaf",
        "sync-once",
        "--workspace",
        str(workspace),
        "--apply",
    ]
    unit = manager.render_service_unit(loaded.resolved_workspace)
    assert f'ExecStart=:"{python}" "-m" "dnsleaf"' in unit
    assert "/wrong/" not in unit
    assert "/usr/bin/python3" not in unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/tmp/a b", '"/tmp/a b"'),
        ('/tmp/a"b', '"/tmp/a\\"b"'),
        ("/tmp/a'b", '"/tmp/a\'b"'),
        ("/tmp/a\\b", '"/tmp/a\\\\b"'),
        ("/tmp/%n/${HOME};x", '"/tmp/%%n/${HOME};x"'),
        ("/tmp/a\nb\tc\rd", '"/tmp/a\\x0ab\\x09c\\x0dd"'),
    ],
)
def test_systemd_arguments_escape_expansion_and_control_characters(raw: str, expected: str) -> None:
    assert _systemd_escape_arg(raw) == expected


def test_service_escapes_workspace_path() -> None:
    config = WorkspaceConfig.from_mapping({"workspace_name": "demo"})
    resolved = config.resolve(Path('/tmp/a b/"quotes"/%n/$HOME;tail'))
    unit = SystemdManager().render_service_unit(resolved)
    assert '"/tmp/a b/\\"quotes\\"/%%n/$HOME;tail"' in unit
    assert "ExecStart=:" in unit
    assert len([line for line in unit.splitlines() if line.startswith("ExecStart=")]) == 1


@pytest.mark.parametrize("name", ["../escape", "path/unit", "bad\nname", "%n", "-unit"])
def test_unit_names_cannot_escape_install_directory(name: str) -> None:
    with pytest.raises(ValueError, match="systemd unit name"):
        WorkspaceConfig.from_mapping({"systemd": {"service_name": name}})


def test_timer_rejects_directive_injection() -> None:
    with pytest.raises(ValueError, match="control characters"):
        WorkspaceConfig.from_mapping({"systemd": {"on_boot_sec": "1s\nUnit=other.service"}})


def test_install_copies_rendered_units_into_configured_directory(tmp_path: Path) -> None:
    workspace = scaffold_workspace(tmp_path)
    loaded = WorkspaceStorage().load(workspace)
    manager = SystemdManager()
    resolved = loaded.workspace_config.model_copy(
        update={
            "paths": loaded.workspace_config.paths.model_copy(
                update={
                    "systemd_unit_dir": str(tmp_path / "units"),
                }
            ),
        }
    ).resolve(workspace)
    for kind in ("service", "timer"):
        render = getattr(manager, f"render_{kind}_unit")
        (loaded.paths.rendered_systemd_dir / f"dnsleaf-lab.{kind}").write_text(render(resolved))
    service, timer = manager.install_rendered_units(loaded.paths, resolved)
    assert service.parent == tmp_path / "units"
    assert service.read_text() == manager.render_service_unit(resolved)
    assert timer.read_text() == manager.render_timer_unit(resolved)


def test_service_preserves_dollar_characters_in_installer_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dnsleaf.systemd.sys.executable", "/opt/tool ${HOME} %n/bin/python")
    workspace = WorkspaceConfig.from_defaults().resolve(Path("/tmp/workspace"))
    unit = SystemdManager().render_service_unit(workspace)
    assert 'ExecStart=:"/opt/tool ${HOME} %%n/bin/python" "-m" "dnsleaf"' in unit
