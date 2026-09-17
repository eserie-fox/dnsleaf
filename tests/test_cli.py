from __future__ import annotations

import re
from contextlib import nullcontext
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dnsleaf import cli
from dnsleaf.commands import common
from dnsleaf.config.outside_workspace import OutsideWorkspaceConfig
from dnsleaf.discovery.models import AddressCandidate, DiscoveryResult, SelectionResult
from dnsleaf.dns.models import ProviderVerification
from dnsleaf.models import (
    EntryAddressFamily,
    EntrySourceKind,
    IPAddressFamily,
    SelectedAddress,
    TargetRef,
)
from dnsleaf.version import __version__
from dnsleaf.workspace.models import WorkspaceEntry
from dnsleaf.workspace.reports import (
    ApplyReport,
    DoctorCheck,
    DoctorReport,
    EntryMutationResult,
    RecordSyncOutcome,
    RenderArtifacts,
    SystemdUnitStatus,
    UninstallReport,
    ValidationReport,
    WorkspaceRunReport,
    WorkspaceStatus,
)

runner = CliRunner()


def _plain_help(output: str) -> str:
    """Remove ANSI styling that can split option names into multiple spans."""

    return re.sub(r"\x1b\[[0-9;]*m", "", output)


def _noop_workspace_logging(*args, **kwargs):
    return nullcontext(args[1] if args[1] is not None else Path("."))


class FakeWorkspaceService:
    def init_workspace(self, directory: Path) -> Path:
        return directory

    def validate_workspace(self, workspace: Path) -> ValidationReport:
        return ValidationReport(
            workspace_root=str(workspace),
            workspace_name="lab",
            provider="cloudflare",
            zone_name="example.com",
            zone_id=None,
            token_file=str(workspace / "secrets" / "cloudflare_api_token.txt"),
            entry_count=1,
            enabled_entry_count=1,
        )

    def render_workspace(self, workspace: Path) -> RenderArtifacts:
        return RenderArtifacts(
            workspace_root=str(workspace),
            workspace_name="lab",
            effective_workspace_file=str(workspace / "rendered" / "effective-workspace.json"),
            desired_records_file=str(workspace / "rendered" / "desired-records.json"),
            service_unit_file=str(workspace / "rendered" / "systemd" / "svc.service"),
            timer_unit_file=str(workspace / "rendered" / "systemd" / "svc.timer"),
            desired_record_count=2,
        )

    def apply_workspace(self, workspace: Path, *, prune_managed, run_sync) -> ApplyReport:
        return ApplyReport(
            workspace_root=str(workspace),
            workspace_name="lab",
            service_name="dnsleaf-lab",
            timer_name="dnsleaf-lab",
            installed_service_unit="/etc/systemd/system/dnsleaf-lab.service",
            installed_timer_unit="/etc/systemd/system/dnsleaf-lab.timer",
            prune_managed=False,
            immediate_sync_requested=False,
            immediate_sync_ran=False,
            render=self.render_workspace(workspace),
            sync_report=None,
        )

    def plan_workspace(self, workspace: Path, *, prune_managed) -> WorkspaceRunReport:
        return WorkspaceRunReport(
            workspace_name="lab",
            dry_run=True,
            record_outcomes=[
                RecordSyncOutcome(
                    entry_name="web",
                    source_kind=EntrySourceKind.LXC,
                    source_id=101,
                    family=IPAddressFamily.IPV6,
                    fqdn="host.example.com",
                    record_type="AAAA",
                    value_source="dynamic",
                    selection_status="selected",
                    selected_value="2001:4860:abcd:1234::3d6",
                    status="planned",
                    message="changes planned",
                )
            ],
        )

    def sync_once(self, workspace: Path, *, apply: bool, prune_managed) -> WorkspaceRunReport:
        return WorkspaceRunReport(workspace_name="lab", dry_run=not apply)

    def provider_verify(self, workspace: Path) -> ProviderVerification:
        return ProviderVerification(
            provider="cloudflare",
            token_file=str(workspace / "secrets" / "cloudflare_api_token.txt"),
            zone_id="zone-123",
            zone_name="example.com",
            record_listing_succeeded=True,
        )

    def uninstall_workspace(self, workspace: Path, *, purge: bool) -> UninstallReport:
        return UninstallReport(
            workspace_root=str(workspace),
            workspace_name="lab",
            service_name="dnsleaf-lab",
            timer_name="dnsleaf-lab",
            systemctl_available=True,
            service_stopped=True,
            timer_stopped=True,
            timer_disabled=True,
            service_unit_removed=True,
            timer_unit_removed=True,
            daemon_reloaded=True,
            service_reset_failed=True,
            timer_reset_failed=True,
            removed_paths=[str(workspace / "rendered"), str(workspace / "runtime")],
            kept_paths=[str(workspace / "workspace.yaml")],
            purged=purge,
            manual_cleanup_hint=None if purge else f"rm -rf {workspace}",
        )

    def status_workspace(self, workspace: Path) -> WorkspaceStatus:
        return WorkspaceStatus(
            workspace_root=str(workspace),
            workspace_name="lab",
            provider="cloudflare",
            zone_name="example.com",
            zone_id=None,
            token_file=str(workspace / "secrets" / "cloudflare_api_token.txt"),
            entry_count=1,
            enabled_entry_count=1,
            rendered_artifacts={
                "effective_workspace": True,
                "desired_records": True,
                "service_unit": True,
                "timer_unit": True,
            },
            runtime_dir_exists=True,
            runtime_log_file=str(workspace / "runtime" / "logs" / "dnsleaf.log"),
            runtime_log_file_exists=True,
            managed_active_count=1,
            managed_stale_count=0,
            service_status=SystemdUnitStatus(
                unit_name="dnsleaf-lab.service",
                available=True,
                active_state="active",
            ),
            timer_status=SystemdUnitStatus(
                unit_name="dnsleaf-lab.timer",
                available=True,
                active_state="active",
            ),
        )

    def doctor_workspace(self, workspace: Path) -> DoctorReport:
        return DoctorReport(
            workspace_root=str(workspace),
            checks=[DoctorCheck(name="workspace_dir", status="ok", message="ok")],
        )


class FakeEntryService:
    def add_entry(self, *args, **kwargs) -> EntryMutationResult:
        return EntryMutationResult(operation="add", changed=True, message="added entry web")

    def list_entries(self, workspace: Path) -> list[WorkspaceEntry]:
        return [
            WorkspaceEntry(
                name="edge",
                source_kind=EntrySourceKind.STATIC,
                fqdn="edge.example.com",
                family=EntryAddressFamily.BOTH,
                enabled=True,
                static_ipv4="93.184.216.34",
                static_ipv6="2001:4860:abcd:1234::88",
            )
        ]

    def update_entry(self, *args, **kwargs) -> EntryMutationResult:
        return EntryMutationResult(operation="update", changed=True, message="updated entry web")

    def remove_entry(self, *args, **kwargs) -> EntryMutationResult:
        return EntryMutationResult(operation="remove", changed=True, message="removed entry web")

    def set_enabled(self, *args, **kwargs) -> EntryMutationResult:
        return EntryMutationResult(operation="update", changed=True, message="updated entry web")


class FakeDebugRunner:
    def discover_target_families(
        self,
        target: TargetRef,
        *,
        families,
        policy: str,
        loaded_workspace=None,
    ):
        _ = loaded_workspace
        discovery = DiscoveryResult(
            target=target,
            backend="fake",
            candidates=[
                AddressCandidate(
                    family=IPAddressFamily.IPV4,
                    interface="eth0",
                    address="93.184.216.34",
                    prefix_length=32,
                    source="fake",
                ),
                AddressCandidate(
                    family=IPAddressFamily.IPV6,
                    interface="eth0",
                    address="2001:4860:abcd:1234::3d6",
                    prefix_length=128,
                    source="fake",
                ),
            ],
        )
        selections = {
            family: SelectionResult(
                target=target,
                family=family,
                policy=policy,
                status="selected",
                selected=SelectedAddress(
                    target=target,
                    family=family,
                    address="93.184.216.34"
                    if family is IPAddressFamily.IPV4
                    else "2001:4860:abcd:1234::3d6",
                    prefix_length=32 if family is IPAddressFamily.IPV4 else 128,
                    interface="eth0",
                    selection_policy=policy,
                    source="fake",
                    reason="selected",
                ),
                reason="selected",
            )
            for family in families
        }
        return discovery, selections


def test_init_command(monkeypatch) -> None:
    monkeypatch.setattr(common, "workspace_service", lambda ctx: FakeWorkspaceService())

    result = runner.invoke(cli.app, ["init", "/tmp/lab"])

    assert result.exit_code == 0
    assert "workspace=/tmp/lab" in result.stdout


def test_entry_add_lxc_command(monkeypatch) -> None:
    monkeypatch.setattr(common, "entry_service", lambda ctx: FakeEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        [
            "entry",
            "add",
            "lxc",
            "--workspace",
            "/tmp/lab",
            "--id",
            "101",
            "--fqdn",
            "host.example.com",
            "--name",
            "web",
            "--family",
            "ipv6",
        ],
    )

    assert result.exit_code == 0
    assert "added entry web" in result.stdout


def test_entry_add_local_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CapturingEntryService(FakeEntryService):
        def add_entry(self, *args, **kwargs) -> EntryMutationResult:
            _ = args
            captured.update(kwargs)
            return EntryMutationResult(operation="add", changed=True, message="added entry self")

    monkeypatch.setattr(common, "entry_service", lambda ctx: CapturingEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        [
            "entry",
            "add",
            "local",
            "--workspace",
            "/tmp/lab",
            "--fqdn",
            "self.example.com",
            "--name",
            "self",
            "--family",
            "ipv6",
        ],
    )

    assert result.exit_code == 0
    assert "added entry self" in result.stdout
    assert captured["source_kind"] == "local"
    assert "source_id" not in captured


def test_entry_add_static_command(monkeypatch) -> None:
    monkeypatch.setattr(common, "entry_service", lambda ctx: FakeEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        [
            "entry",
            "add",
            "static",
            "--workspace",
            "/tmp/lab",
            "--fqdn",
            "edge.example.com",
            "--name",
            "edge",
            "--family",
            "both",
            "--ipv4",
            "93.184.216.34",
            "--ipv6",
            "2001:4860:abcd:1234::88",
        ],
    )

    assert result.exit_code == 0
    assert "added entry web" in result.stdout


def test_entry_add_command_accepts_auto_ttl(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CapturingEntryService(FakeEntryService):
        def add_entry(self, *args, **kwargs) -> EntryMutationResult:
            _ = args
            captured.update(kwargs)
            return EntryMutationResult(operation="add", changed=True, message="added entry web")

    monkeypatch.setattr(common, "entry_service", lambda ctx: CapturingEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        [
            "entry",
            "add",
            "lxc",
            "--workspace",
            "/tmp/lab",
            "--id",
            "101",
            "--fqdn",
            "host.example.com",
            "--name",
            "web",
            "--family",
            "ipv6",
            "--ttl",
            "auto",
        ],
    )

    assert result.exit_code == 0
    assert captured["ttl"] == "auto"


def test_entry_update_command_accepts_auto_ttl(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CapturingEntryService(FakeEntryService):
        def update_entry(self, *args, **kwargs) -> EntryMutationResult:
            _ = args
            captured.update(kwargs)
            return EntryMutationResult(
                operation="update",
                changed=True,
                message="updated entry web",
            )

    monkeypatch.setattr(common, "entry_service", lambda ctx: CapturingEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        [
            "entry",
            "update",
            "web",
            "--workspace",
            "/tmp/lab",
            "--ttl",
            "auto",
        ],
    )

    assert result.exit_code == 0
    assert captured["ttl"] == "auto"


def test_entry_update_command_leaves_proxied_unchanged_when_omitted(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CapturingEntryService(FakeEntryService):
        def update_entry(self, *args, **kwargs) -> EntryMutationResult:
            _ = args
            captured.update(kwargs)
            return EntryMutationResult(
                operation="update",
                changed=True,
                message="updated entry web",
            )

    monkeypatch.setattr(common, "entry_service", lambda ctx: CapturingEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        ["entry", "update", "web", "--workspace", "/tmp/lab"],
    )

    assert result.exit_code == 0
    assert captured["proxied"] is None
    assert captured["inherit_proxied"] is False


def test_entry_update_command_sets_proxied_true(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CapturingEntryService(FakeEntryService):
        def update_entry(self, *args, **kwargs) -> EntryMutationResult:
            _ = args
            captured.update(kwargs)
            return EntryMutationResult(
                operation="update",
                changed=True,
                message="updated entry web",
            )

    monkeypatch.setattr(common, "entry_service", lambda ctx: CapturingEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        ["entry", "update", "web", "--workspace", "/tmp/lab", "--proxied"],
    )

    assert result.exit_code == 0
    assert captured["proxied"] is True
    assert captured["inherit_proxied"] is False


def test_entry_update_command_sets_proxied_false(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CapturingEntryService(FakeEntryService):
        def update_entry(self, *args, **kwargs) -> EntryMutationResult:
            _ = args
            captured.update(kwargs)
            return EntryMutationResult(
                operation="update",
                changed=True,
                message="updated entry web",
            )

    monkeypatch.setattr(common, "entry_service", lambda ctx: CapturingEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        ["entry", "update", "web", "--workspace", "/tmp/lab", "--no-proxied"],
    )

    assert result.exit_code == 0
    assert captured["proxied"] is False
    assert captured["inherit_proxied"] is False


def test_entry_update_command_can_inherit_workspace_proxied_default(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CapturingEntryService(FakeEntryService):
        def update_entry(self, *args, **kwargs) -> EntryMutationResult:
            _ = args
            captured.update(kwargs)
            return EntryMutationResult(
                operation="update",
                changed=True,
                message="updated entry web",
            )

    monkeypatch.setattr(common, "entry_service", lambda ctx: CapturingEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        ["entry", "update", "web", "--workspace", "/tmp/lab", "--inherit-proxied"],
    )

    assert result.exit_code == 0
    assert captured["proxied"] is None
    assert captured["inherit_proxied"] is True


def test_entry_add_command_accepts_no_proxied(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CapturingEntryService(FakeEntryService):
        def add_entry(self, *args, **kwargs) -> EntryMutationResult:
            _ = args
            captured.update(kwargs)
            return EntryMutationResult(operation="add", changed=True, message="added entry web")

    monkeypatch.setattr(common, "entry_service", lambda ctx: CapturingEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(
        cli.app,
        [
            "entry",
            "add",
            "lxc",
            "--workspace",
            "/tmp/lab",
            "--id",
            "101",
            "--fqdn",
            "host.example.com",
            "--name",
            "web",
            "--family",
            "ipv6",
            "--no-proxied",
        ],
    )

    assert result.exit_code == 0
    assert captured["proxied"] is False


@pytest.mark.parametrize("color", [False, True], ids=["plain", "color"])
def test_entry_update_help_shows_proxied_flags(color: bool) -> None:
    result = runner.invoke(
        cli.app,
        ["entry", "update", "--help"],
        color=color,
        env={"FORCE_COLOR": "1" if color else None, "NO_COLOR": None if color else "1"},
    )

    assert result.exit_code == 0
    help_text = _plain_help(result.output)
    assert "--proxied" in help_text
    assert "--no-proxied" in help_text
    assert "--inherit-proxied" in help_text


def test_entry_add_defaults_workspace_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(common, "entry_service", lambda ctx: FakeEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli.app,
        [
            "entry",
            "add",
            "lxc",
            "--id",
            "101",
            "--fqdn",
            "host.example.com",
            "--name",
            "web",
            "--family",
            "ipv6",
        ],
    )

    assert result.exit_code == 0
    assert "added entry web" in result.stdout


def test_entry_list_shows_static_fields(monkeypatch) -> None:
    monkeypatch.setattr(common, "entry_service", lambda ctx: FakeEntryService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(cli.app, ["entry", "list", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "family=both" in result.stdout
    assert "ipv4=93.184.216.34" in result.stdout
    assert "ipv6=2001:4860:abcd:1234::88" in result.stdout


def test_provider_verify_command(monkeypatch) -> None:
    monkeypatch.setattr(common, "workspace_service", lambda ctx: FakeWorkspaceService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(cli.app, ["provider", "verify", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "provider=cloudflare" in result.stdout


def test_validate_defaults_workspace_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(common, "workspace_service", lambda ctx: FakeWorkspaceService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 0
    assert "workspace=lab" in result.stdout


def test_status_reports_runtime_log_fields(monkeypatch) -> None:
    monkeypatch.setattr("dnsleaf.commands.workspace.locate_workspace", lambda path: path)
    monkeypatch.setattr(common, "workspace_service", lambda ctx: FakeWorkspaceService())

    result = runner.invoke(cli.app, ["status", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "runtime_exists=True" in result.stdout
    assert "log_file=/tmp/lab/runtime/logs/dnsleaf.log" in result.stdout


def test_uninstall_command(monkeypatch) -> None:
    monkeypatch.setattr(common, "require_root", lambda operation: None)
    monkeypatch.setattr(common, "workspace_service", lambda ctx: FakeWorkspaceService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(cli.app, ["uninstall", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "service_stopped=True" in result.stdout
    assert "service_reset_failed=True" in result.stdout
    assert "System installation artifacts have been removed." in result.stdout


def test_plan_command_uses_record_outcomes(monkeypatch) -> None:
    monkeypatch.setattr(common, "workspace_service", lambda ctx: FakeWorkspaceService())
    monkeypatch.setattr(common, "workspace_command_logging", _noop_workspace_logging)

    result = runner.invoke(cli.app, ["plan", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "entry=web" in result.stdout
    assert "type=AAAA" in result.stdout


def test_discover_command_reports_both_families(monkeypatch) -> None:
    monkeypatch.setattr(common, "debug_runner", lambda ctx: FakeDebugRunner())
    monkeypatch.setattr(common, "require_root", lambda *args, **kwargs: False)

    result = runner.invoke(cli.app, ["discover", "lxc", "101", "--family", "both"])

    assert result.exit_code == 0
    assert "candidate family=ipv4" in result.stdout
    assert "candidate family=ipv6" in result.stdout
    assert "family=ipv4 status=selected" in result.stdout
    assert "family=ipv6 status=selected" in result.stdout


def test_discover_local_command_reports_target_without_id(monkeypatch) -> None:
    monkeypatch.setattr(common, "debug_runner", lambda ctx: FakeDebugRunner())
    monkeypatch.setattr(common, "require_root", lambda *args, **kwargs: False)

    result = runner.invoke(cli.app, ["discover", "local", "--family", "both"])

    assert result.exit_code == 0
    assert "target=local backend=fake" in result.stdout
    assert "candidate family=ipv4" in result.stdout
    assert "candidate family=ipv6" in result.stdout


def test_discover_local_json_omits_target_id(monkeypatch) -> None:
    monkeypatch.setattr(common, "debug_runner", lambda ctx: FakeDebugRunner())
    monkeypatch.setattr(common, "require_root", lambda *args, **kwargs: False)

    result = runner.invoke(cli.app, ["discover", "local", "--family", "ipv6", "--json"])

    assert result.exit_code == 0
    assert '"kind": "local"' in result.stdout
    assert '"id"' not in result.stdout


def test_validate_without_workspace_fails_outside_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "Unable to locate a complete dnsleaf workspace" in result.output
    assert str(tmp_path) in result.output
    assert "workspace.yaml, entries.yaml" in result.output


@pytest.mark.parametrize("color", [False, True], ids=["plain", "color"])
def test_root_help_does_not_expose_config_option(color: bool) -> None:
    result = runner.invoke(
        cli.app,
        ["--help"],
        color=color,
        env={"FORCE_COLOR": "1" if color else None, "NO_COLOR": None if color else "1"},
    )

    assert result.exit_code == 0
    assert "--config" not in _plain_help(result.stdout)


def test_version_option_reports_package_version() -> None:
    result = runner.invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"{__version__}\n"


def test_root_group_without_subcommand_shows_help() -> None:
    result = runner.invoke(cli.app, [])

    assert "Usage:" in result.output
    assert "Manage workspace-driven Cloudflare DDNS" in result.output
    assert "Missing command" not in result.output


def test_entry_group_without_subcommand_shows_help() -> None:
    result = runner.invoke(cli.app, ["entry"])

    assert "Usage:" in result.output
    assert "Manage workspace entries." in result.output
    assert "Missing command" not in result.output


def test_entry_add_group_without_subcommand_shows_help() -> None:
    result = runner.invoke(cli.app, ["entry", "add"])

    assert "Usage:" in result.output
    assert "Add a new workspace entry." in result.output
    assert "Missing command" not in result.output


def test_provider_group_without_subcommand_shows_help() -> None:
    result = runner.invoke(cli.app, ["provider"])

    assert "Usage:" in result.output
    assert "Provider-specific operations." in result.output
    assert "Missing command" not in result.output


def test_discover_group_without_subcommand_shows_help() -> None:
    result = runner.invoke(cli.app, ["discover"])

    assert "Usage:" in result.output
    assert "Run low-level discovery/debug commands." in result.output
    assert "Missing command" not in result.output


def test_apply_fails_fast_when_privileges_are_required(monkeypatch) -> None:
    monkeypatch.setattr("dnsleaf.util.privilege.os.geteuid", lambda: 1000)
    result = runner.invoke(cli.app, ["apply", "--workspace", "/tmp/lab"])
    assert result.exit_code == 1


def test_removed_sudo_option_is_rejected() -> None:
    result = runner.invoke(cli.app, ["plan", "--sudo"])
    assert result.exit_code == 2


def test_validate_json_permission_error_returns_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    def denied(*args, **kwargs):
        raise PermissionError("workspace file is not readable")

    monkeypatch.setattr(common, "workspace_command_logging", denied)
    result = runner.invoke(cli.app, ["validate", "--json"])
    assert result.exit_code == 1
    import json

    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert isinstance(payload["error"], str)


def test_root_callback_uses_outside_workspace_config_and_configures_default_logging(
    monkeypatch,
) -> None:
    monkeypatch.setattr("dnsleaf.commands.workspace.locate_workspace", lambda path: path)
    calls: dict[str, object] = {}
    real_from_defaults = OutsideWorkspaceConfig.from_defaults

    def fake_from_defaults() -> OutsideWorkspaceConfig:
        calls["defaults_loaded"] = True
        return real_from_defaults()

    def fake_configure_default_logging(*, stream_name, level, fmt) -> None:
        calls["stream_name"] = stream_name
        calls["level"] = level
        calls["format"] = fmt

    monkeypatch.setattr(
        OutsideWorkspaceConfig,
        "from_defaults",
        staticmethod(fake_from_defaults),
    )
    monkeypatch.setattr(cli, "configure_default_logging", fake_configure_default_logging)
    monkeypatch.setattr(common, "workspace_service", lambda ctx: FakeWorkspaceService())

    result = runner.invoke(
        cli.app,
        ["status", "--workspace", "/tmp/lab"],
    )

    assert result.exit_code == 0
    assert calls["defaults_loaded"] is True
    assert calls["stream_name"] == "stderr"
    assert calls["level"] == (
        OutsideWorkspaceConfig.from_defaults().dnsleaf_logging.resolved_level()
    )
