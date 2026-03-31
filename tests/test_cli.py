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
    ValidationReport,
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

    def status_workspace(self, workspace: Path):
        raise NotImplementedError

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


def test_provider_verify_command(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_workspace_service", lambda config_path: FakeWorkspaceService())

    result = runner.invoke(cli.app, ["provider", "verify", "--workspace", "/tmp/lab"])

    assert result.exit_code == 0
    assert "provider=cloudflare" in result.stdout
