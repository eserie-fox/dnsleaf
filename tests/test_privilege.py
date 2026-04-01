from __future__ import annotations

from pathlib import Path

import click
import pytest
import typer.main
import yaml  # type: ignore[import-untyped]
from click.core import ParameterSource

from arbor_ddns import cli
from arbor_ddns.commands import _privilege_analysis as privilege_analysis
from arbor_ddns.commands._privilege import (
    PermissionOperationError,
    UnsupportedSudoReexecParameterError,
    _option_tokens,
    command_args_from_ctx,
    ensure_root_privileges,
)
from arbor_ddns.models import TargetKind
from arbor_ddns.workspace.entries import EntryService


def _make_command_context(argv: list[str]) -> click.Context:
    click_app = typer.main.get_command(cli.app)
    root_ctx = click_app.make_context("arbor-ddns", argv, resilient_parsing=False)
    command_name = argv[0]
    command = click_app.commands[command_name]
    return command.make_context(command_name, argv[1:], parent=root_ctx, resilient_parsing=False)


@pytest.mark.parametrize(
    "argv",
    [
        ["apply", "--workspace", "/tmp/lab", "--no-run-sync", "--sudo"],
        ["apply", "--workspace", "/tmp/lab", "--no-prune-managed", "--sudo"],
        ["plan", "--workspace", "/tmp/lab", "--no-prune-managed", "--sudo"],
        ["sync-once", "--workspace", "/tmp/lab", "--no-prune-managed", "--sudo"],
    ],
)
def test_command_args_from_ctx_round_trips_workspace_boolean_flags(argv: list[str]) -> None:
    original_ctx = _make_command_context(argv)
    rebuilt_argv = command_args_from_ctx(original_ctx)
    round_tripped_ctx = _make_command_context(rebuilt_argv)

    assert round_tripped_ctx.params == original_ctx.params


def test_option_tokens_use_secondary_flag_for_explicit_false() -> None:
    @click.command()
    @click.option("--feature/--no-feature", default=True)
    def demo(feature: bool) -> None:
        _ = feature

    option = demo.params[0]

    assert _option_tokens(option, False, source=ParameterSource.COMMANDLINE) == ["--no-feature"]


def test_option_tokens_fail_fast_for_unsupported_multiple_shape() -> None:
    @click.command()
    @click.option("--label", multiple=True)
    def demo(label: tuple[str, ...]) -> None:
        _ = label

    option = demo.params[0]

    with pytest.raises(UnsupportedSudoReexecParameterError, match="multiple=True"):
        _option_tokens(option, ("one", "two"), source=ParameterSource.COMMANDLINE)


def test_ensure_root_privileges_fails_fast_without_sudo(monkeypatch) -> None:
    monkeypatch.setattr("arbor_ddns.commands._privilege.current_user_is_root", lambda: False)

    try:
        ensure_root_privileges(
            operation="apply",
            reasons=["will manage system services via systemctl"],
            sudo_requested=False,
            command_args=["apply", "--workspace", "/tmp/demo"],
        )
    except PermissionOperationError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected PermissionOperationError")

    assert "apply requires elevated privileges" in message
    assert "will manage system services via systemctl" in message
    assert "Retry with: arbor-ddns apply --workspace /tmp/demo --sudo" in message


def test_ensure_root_privileges_reexecs_with_sudo(monkeypatch) -> None:
    captured: list[list[str]] = []

    monkeypatch.setattr("arbor_ddns.commands._privilege.current_user_is_root", lambda: False)
    monkeypatch.setattr("arbor_ddns.commands._privilege.command_available", lambda command: True)
    monkeypatch.setattr(
        "arbor_ddns.commands._privilege._exec_with_sudo",
        lambda args: captured.append(args),
    )
    monkeypatch.setattr("arbor_ddns.commands._privilege.Path.exists", lambda self: True)
    monkeypatch.setattr("arbor_ddns.commands._privilege.os.access", lambda path, mode: True)

    result = ensure_root_privileges(
        operation="apply",
        reasons=["will manage system services via systemctl"],
        sudo_requested=True,
        command_args=["apply", "--workspace", "/tmp/demo"],
    )

    assert result is True
    assert captured
    assert captured[0][0] == "sudo"
    assert "--sudo" in captured[0]


def test_ensure_root_privileges_falls_back_to_python_module_when_console_script_missing(
    monkeypatch,
) -> None:
    captured: list[list[str]] = []

    monkeypatch.setattr("arbor_ddns.commands._privilege.current_user_is_root", lambda: False)
    monkeypatch.setattr("arbor_ddns.commands._privilege.command_available", lambda command: True)
    monkeypatch.setattr(
        "arbor_ddns.commands._privilege._exec_with_sudo",
        lambda args: captured.append(args),
    )
    monkeypatch.setattr("arbor_ddns.commands._privilege.Path.exists", lambda self: False)
    monkeypatch.setattr("arbor_ddns.commands._privilege.sys.executable", "/opt/venv/bin/python")

    result = ensure_root_privileges(
        operation="apply",
        reasons=["will manage system services via systemctl"],
        sudo_requested=True,
        command_args=["apply", "--workspace", "/tmp/demo"],
    )

    assert result is True
    assert captured == [
        [
            "sudo",
            "/opt/venv/bin/python",
            "-m",
            "arbor_ddns",
            "apply",
            "--workspace",
            "/tmp/demo",
            "--sudo",
        ]
    ]


def test_ensure_root_privileges_does_not_reexec_when_already_root(monkeypatch) -> None:
    monkeypatch.setattr("arbor_ddns.commands._privilege.current_user_is_root", lambda: True)
    monkeypatch.setattr(
        "arbor_ddns.commands._privilege._exec_with_sudo",
        lambda args: (_ for _ in ()).throw(AssertionError("should not re-exec")),
    )

    result = ensure_root_privileges(
        operation="plan",
        reasons=["will execute PVE guest discovery via pct exec"],
        sudo_requested=True,
        command_args=["plan", "--workspace", "/tmp/demo"],
    )

    assert result is False


def test_ensure_root_privileges_reports_missing_sudo_binary(monkeypatch) -> None:
    monkeypatch.setattr("arbor_ddns.commands._privilege.current_user_is_root", lambda: False)
    monkeypatch.setattr("arbor_ddns.commands._privilege.command_available", lambda command: False)

    try:
        ensure_root_privileges(
            operation="discover lxc",
            reasons=["will execute PVE guest discovery via pct exec"],
            sudo_requested=True,
            command_args=["discover", "lxc", "101"],
        )
    except PermissionOperationError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected PermissionOperationError")

    assert "`--sudo` was requested, but `sudo` is not available in PATH." in message
    assert "Run this command as root instead: arbor-ddns discover lxc 101" in message


def test_analyze_status_root_requirements_reports_unreadable_workspace_parent(monkeypatch) -> None:
    root_workspace = Path("/root/orange-ddns-config")
    real_can_read_directory = privilege_analysis.can_read_directory

    def fake_can_read_directory(path: Path) -> bool:
        if path == Path("/root"):
            return False
        return real_can_read_directory(path)

    monkeypatch.setattr(privilege_analysis, "can_read_directory", fake_can_read_directory)

    reasons = privilege_analysis.analyze_status_root_requirements(root_workspace)

    assert any("workspace parent directory is not readable" in reason for reason in reasons)


def test_analyze_apply_root_requirements_reports_unwritable_targets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
    )

    token_path = workspace / "secrets" / "cloudflare_api_token.txt"
    log_path = workspace / "runtime" / "logs" / "arbor-ddns.log"
    rendered_dir = workspace / "rendered"
    state_dir = workspace / "state"
    unit_dir = Path("/etc/systemd/system")
    real_can_read_file = privilege_analysis.can_read_file

    def fake_can_read_file(path: Path) -> bool:
        if path == token_path:
            return False
        return real_can_read_file(path)

    def fake_can_write_file(path: Path) -> bool:
        if path == log_path:
            return False
        return True

    def fake_can_write_directory(path: Path) -> bool:
        if path in {rendered_dir, state_dir, unit_dir}:
            return False
        return True

    monkeypatch.setattr(privilege_analysis, "can_read_file", fake_can_read_file)
    monkeypatch.setattr(privilege_analysis, "can_write_file", fake_can_write_file)
    monkeypatch.setattr(privilege_analysis, "can_write_directory", fake_can_write_directory)

    reasons = privilege_analysis.analyze_apply_root_requirements(workspace)

    assert any("token file is not readable" in reason for reason in reasons)
    assert any("workspace runtime log path is not writable" in reason for reason in reasons)
    assert any("rendered output path is not writable" in reason for reason in reasons)
    assert any("state path is not writable" in reason for reason in reasons)
    assert any("systemd unit directory is not writable" in reason for reason in reasons)
    assert "will manage system services via systemctl" in reasons
    assert "will execute PVE guest discovery via pct exec" in reasons


def test_analyze_uninstall_root_requirements_reports_delete_targets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    payload = yaml.safe_load((workspace / "workspace.yaml").read_text(encoding="utf-8"))
    unit_dir = tmp_path / "units"
    payload["paths"]["systemd_unit_dir"] = str(unit_dir)
    (workspace / "workspace.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "arbor-ddns-lab.service").write_text("service\n", encoding="utf-8")
    (unit_dir / "arbor-ddns-lab.timer").write_text("timer\n", encoding="utf-8")

    rendered_dir = workspace / "rendered"
    runtime_dir = workspace / "runtime"
    service_unit = unit_dir / "arbor-ddns-lab.service"
    timer_unit = unit_dir / "arbor-ddns-lab.timer"

    def fake_can_delete_path(path: Path) -> bool:
        return path not in {
            rendered_dir,
            runtime_dir,
            workspace.resolve(),
            service_unit,
            timer_unit,
        }

    monkeypatch.setattr(privilege_analysis, "can_delete_path", fake_can_delete_path)
    monkeypatch.setattr(privilege_analysis, "command_available", lambda command: True)

    reasons = privilege_analysis.analyze_uninstall_root_requirements(workspace, purge=True)

    assert "will manage system services via systemctl" in reasons
    assert any("installed service unit is not removable" in reason for reason in reasons)
    assert any("installed timer unit is not removable" in reason for reason in reasons)
    assert any("generated path is not removable" in reason for reason in reasons)
    assert any("workspace root is not removable" in reason for reason in reasons)


def test_analyze_plan_root_requirements_ignores_static_entries_for_pve_reason(
    tmp_path: Path,
) -> None:
    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace,
        name="edge",
        source_kind="static",
        fqdn="edge.example.com",
        family="both",
        static_ipv4="93.184.216.34",
        static_ipv6="2408:8266:5003:506a::88",
    )

    reasons = privilege_analysis.analyze_plan_root_requirements(workspace)

    assert "will execute PVE guest discovery via pct exec" not in reasons
    assert "will execute PVE guest discovery via qm agent" not in reasons


def test_analyze_discover_root_requirements_for_local_does_not_add_pve_reasons() -> None:
    reasons = privilege_analysis.analyze_discover_root_requirements(
        TargetKind.LOCAL,
        workspace=None,
    )

    assert "will execute PVE guest discovery via pct exec" not in reasons
    assert "will execute PVE guest discovery via qm agent" not in reasons


def test_analyze_plan_root_requirements_ignores_local_entries_for_pve_reason(
    tmp_path: Path,
) -> None:
    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace,
        name="self",
        source_kind="local",
        fqdn="self.example.com",
        family="both",
    )

    reasons = privilege_analysis.analyze_plan_root_requirements(workspace)

    assert "will execute PVE guest discovery via pct exec" not in reasons
    assert "will execute PVE guest discovery via qm agent" not in reasons
