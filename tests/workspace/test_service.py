from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeDiscoveryBackend, FakeDNSProvider, FakeSystemdManager

from arbor_ddns.config import AppConfig
from arbor_ddns.models import TargetKind
from arbor_ddns.sync.runner import SyncRunner
from arbor_ddns.workspace.entries import EntryService
from arbor_ddns.workspace.service import WorkspaceService
from arbor_ddns.workspace.state import load_last_apply, load_managed_records
from arbor_ddns.workspace.storage import WorkspaceStorage


def _service(tmp_path: Path, provider: FakeDNSProvider) -> WorkspaceService:
    app_config = AppConfig.from_mapping({"systemd": {"unit_dir": str(tmp_path / "units")}})
    storage = WorkspaceStorage(app_config)
    systemd_manager = FakeSystemdManager(tmp_path / "units")
    runner = SyncRunner(
        app_config=app_config,
        discovery_backends={
            TargetKind.LXC.value: FakeDiscoveryBackend(),
            TargetKind.VM.value: FakeDiscoveryBackend(),
        },
        provider_factory=lambda loaded: provider,
    )
    return WorkspaceService(
        app_config=app_config,
        storage=storage,
        systemd_manager=systemd_manager,
        renderer=None,
        runner=runner,
    )


def test_provider_verify_uses_workspace_provider(tmp_path: Path, monkeypatch) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    service = _service(tmp_path, FakeDNSProvider())
    monkeypatch.setattr(
        "arbor_ddns.workspace.service.CloudflareDNSProvider",
        lambda config: FakeDNSProvider(),
    )

    verification = service.provider_verify(workspace_dir)

    assert verification.provider == "cloudflare"
    assert verification.zone_id == "zone-123"


def test_sync_once_updates_managed_record_state_and_prunes_safely(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    entries = EntryService(
        WorkspaceStorage(AppConfig.from_mapping({"systemd": {"unit_dir": str(tmp_path / "units")}}))
    )
    # Recreate the service after entry writes so storage and runner share the same app config.
    entries.add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
    )

    provider = FakeDNSProvider()
    service = _service(tmp_path, provider)

    first_report = service.sync_once(workspace_dir, apply=True, prune_managed=False)
    managed_state = load_managed_records(service._storage.paths_for(workspace_dir))

    assert first_report.entry_outcomes[0].applied is True
    assert len(managed_state.records) == 1
    assert managed_state.records[0].state == "active"

    EntryService(service._storage).remove_entry(workspace_dir, name="web")
    second_report = service.sync_once(workspace_dir, apply=True, prune_managed=False)
    managed_state = load_managed_records(service._storage.paths_for(workspace_dir))

    assert second_report.entry_outcomes == []
    assert len(managed_state.records) == 1
    assert managed_state.records[0].state == "stale"

    third_report = service.sync_once(workspace_dir, apply=True, prune_managed=True)
    managed_state = load_managed_records(service._storage.paths_for(workspace_dir))

    assert third_report.prune_outcomes[0].status == "applied"
    assert managed_state.records == []


def test_apply_renders_installs_units_and_records_last_apply(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
    )
    provider = FakeDNSProvider()
    service = _service(tmp_path, provider)

    report = service.apply_workspace(workspace_dir, run_sync=True)
    last_apply = load_last_apply(service._storage.paths_for(workspace_dir))

    assert report.immediate_sync_ran is True
    assert Path(report.installed_service_unit).exists()
    assert Path(report.installed_timer_unit).exists()
    assert last_apply is not None
    assert last_apply.immediate_sync_ran is True


def test_status_aggregates_state_and_systemd(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
    )
    service = _service(tmp_path, FakeDNSProvider())
    service.render_workspace(workspace_dir)
    service.apply_workspace(workspace_dir, run_sync=False)

    status = service.status_workspace(workspace_dir)

    assert status.workspace_name == "lab"
    assert status.entry_count == 1
    assert status.rendered_artifacts["effective_workspace"] is True
    assert status.service_status.active_state == "active"


def test_doctor_reports_missing_token_file(tmp_path: Path) -> None:
    service = WorkspaceService()
    workspace_dir = tmp_path / "lab"
    service.init_workspace(workspace_dir)

    report = service.doctor_workspace(workspace_dir)

    token_check = next(check for check in report.checks if check.name == "token_file")
    assert token_check.status == "error"
