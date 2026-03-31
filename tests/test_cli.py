from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arbor_ddns import cli
from arbor_ddns.dns.models import ProviderVerification
from arbor_ddns.sync.runner import WorkspaceRunReport
from arbor_ddns.workspace.models import (
    DoctorCheck,
    DoctorReport,
    EntryMutationResult,
    RenderArtifacts,
    SystemdUnitStatus,
    UninstallReport,
    ValidationReport,
    WorkspaceStatus,
)
from arbor_ddns.workspace.service import ApplyReport

runner = CliRunner()


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
            desired_record_count=1,
        )

    def apply_workspace(self, workspace: Path, *, prune_managed, run_sync) -> ApplyReport:
        return ApplyReport(
            workspace_root=str(workspace),
            workspace_name="lab",
            service_name="arbor-ddns-lab",
            timer_name="arbor-ddns-lab",
            installed_service_unit="/etc/systemd/system/arbor-ddns-lab.service",
            installed_timer_unit="/etc/systemd/system/arbor-ddns-lab.timer",
            prune_managed=False,
            immediate_sync_requested=False,
            immediate_sync_ran=False,
            render=self.render_workspace(workspace),
            sync_report=None,
        )

    def plan_workspace(self, workspace: Path, *, prune_managed) -> WorkspaceRunReport:
        return WorkspaceRunReport(workspace_name="lab", dry_run=True)

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
            service_name="arbor-ddns-lab",
            timer_name="arbor-ddns-lab",
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
            runtime_log_file=str(workspace / "runtime" / "logs" / "arbor-ddns.log"),
            runtime_log_file_exists=True,
            managed_active_count=1,
            managed_stale_count=0,
            service_status=SystemdUnitStatus(
                unit_name="arbor-ddns-lab.service",
                available=True,
                active_state="active",
            ),
            timer_status=SystemdUnitStatus(
                unit_name="arbor-ddns-lab.timer",
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

    def list_entries(self, workspace: Path):
        return []

    def update_entry(self, *args, **kwargs) -> EntryMutationResult:
        return EntryMutationResult(operation="update", changed=True, message="updated entry web")

    def remove_entry(self, *args, **kwargs) -> EntryMutationResult:
        return EntryMutationResult(operation="remove", changed=True, message="removed entry web")

    def set_enabled(self, *args, **kwargs) -> EntryMutationResult:
        return EntryMutationResult(operation="update", changed=True, message="updated entry web")


def test_init_command(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_workspace_service", lambda config_path: FakeWorkspaceService())

    result = runner.invoke(cli.app, ["init", "/tmp/lab"])

    assert result.exit_code == 0
    assert "workspace=/tmp/lab" in result.stdout


def test_entry_add_lxc_command(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_entry_service", lambda config_path: FakeEntryService())

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
        ],
    )

    assert result.exit_code == 0
    assert "added entry web" in result.stdout


def test_entry_add_lxc_defaults_workspace_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_entry_service", lambda config_path: FakeEntryService())
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
        ],
    )

    assert result.exit_code == 0
    assert "added entry web" in result.stdout


def test_provider_verify_command(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_workspace_service", lambda config_path: FakeWorkspaceService())

    result = runner.invoke(cli.app, ["provider", "verify", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "provider=cloudflare" in result.stdout


def test_validate_defaults_workspace_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_workspace_service", lambda config_path: FakeWorkspaceService())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 0
    assert "workspace=lab" in result.stdout


def test_status_reports_runtime_log_fields(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_workspace_service", lambda config_path: FakeWorkspaceService())

    result = runner.invoke(cli.app, ["status", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "runtime_exists=True" in result.stdout
    assert "log_file=/tmp/lab/runtime/logs/arbor-ddns.log" in result.stdout


def test_uninstall_command(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_workspace_service", lambda config_path: FakeWorkspaceService())

    result = runner.invoke(cli.app, ["uninstall", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "service_stopped=True" in result.stdout
    assert "service_reset_failed=True" in result.stdout
    assert "System installation artifacts have been removed." in result.stdout


def test_validate_without_workspace_fails_outside_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "workspace file not found" in result.stdout or "workspace file not found" in result.stderr
