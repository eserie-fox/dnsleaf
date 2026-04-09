from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeDiscoveryBackend, FakeDNSProvider, FakeSystemdManager

from arbor_ddns.discovery.models import AddressCandidate
from arbor_ddns.dns.models import DNSRecord
from arbor_ddns.logging.runtime import workspace_logging_context
from arbor_ddns.models import IPAddressFamily, TargetKind
from arbor_ddns.sync.runner import SyncRunner
from arbor_ddns.workspace.entries import EntryService
from arbor_ddns.workspace.service import WorkspaceService
from arbor_ddns.workspace.state import load_last_apply, load_managed_records
from arbor_ddns.workspace.storage import WorkspaceStorage


def _service(
    tmp_path: Path,
    provider: FakeDNSProvider,
    *,
    discovery_backend: FakeDiscoveryBackend | None = None,
) -> WorkspaceService:
    storage = WorkspaceStorage()
    systemd_manager = FakeSystemdManager(tmp_path / "units")
    backend = discovery_backend or FakeDiscoveryBackend()
    runner = SyncRunner(
        discovery_backends={
            TargetKind.LXC.value: backend,
            TargetKind.VM.value: backend,
        },
        provider_factory=lambda loaded: provider,
    )
    return WorkspaceService(
        storage=storage,
        systemd_manager=systemd_manager,
        renderer=None,
        runner=runner,
    )


def _service_with_manager(
    tmp_path: Path,
    provider: FakeDNSProvider,
    *,
    discovery_backend: FakeDiscoveryBackend | None = None,
) -> tuple[WorkspaceService, FakeSystemdManager]:
    storage = WorkspaceStorage()
    systemd_manager = FakeSystemdManager(tmp_path / "units")
    backend = discovery_backend or FakeDiscoveryBackend()
    runner = SyncRunner(
        discovery_backends={
            TargetKind.LXC.value: backend,
            TargetKind.VM.value: backend,
        },
        provider_factory=lambda loaded: provider,
    )
    service = WorkspaceService(
        storage=storage,
        systemd_manager=systemd_manager,
        renderer=None,
        runner=runner,
    )
    return service, systemd_manager


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
        WorkspaceStorage()
    )
    entries.add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
    )

    provider = FakeDNSProvider()
    service = _service(tmp_path, provider)

    first_report = service.sync_once(workspace_dir, apply=True, prune_managed=False)
    managed_state = load_managed_records(service._storage.paths_for(workspace_dir))

    assert first_report.record_outcomes[0].applied is True
    assert len(managed_state.records) == 1
    assert managed_state.records[0].state == "active"

    EntryService(service._storage).remove_entry(workspace_dir, name="web")
    second_report = service.sync_once(workspace_dir, apply=True, prune_managed=False)
    managed_state = load_managed_records(service._storage.paths_for(workspace_dir))

    assert second_report.record_outcomes == []
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
        family="ipv6",
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


def test_plan_creates_runtime_log_without_secret_contents(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="both",
    )
    service = _service(tmp_path, FakeDNSProvider())

    with workspace_logging_context(
        workspace_dir,
        command_name="plan",
    ):
        service.plan_workspace(workspace_dir)

    log_file = workspace_dir / "runtime" / "logs" / "arbor-ddns.log"
    log_content = log_file.resolve().read_text(encoding="utf-8")
    assert log_file.is_symlink()
    assert "command=plan" in log_content
    assert "entry=web" in log_content
    assert "secret-token" not in log_content


def test_status_aggregates_state_and_systemd(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace_dir,
        name="edge",
        source_kind="static",
        fqdn="edge.example.com",
        family="both",
        static_ipv4="93.184.216.34",
        static_ipv6="2408:8266:5003:506a::88",
    )
    service = _service(tmp_path, FakeDNSProvider())
    service.render_workspace(workspace_dir)
    service.apply_workspace(workspace_dir, run_sync=False)

    status = service.status_workspace(workspace_dir)

    assert status.workspace_name == "lab"
    assert status.entry_count == 1
    assert status.rendered_artifacts["effective_workspace"] is True
    assert status.runtime_dir_exists is True
    assert status.runtime_log_file.endswith("runtime/logs/arbor-ddns.log")
    assert status.service_status.active_state == "active"


def test_doctor_reports_missing_token_file(tmp_path: Path) -> None:
    service = WorkspaceService()
    workspace_dir = tmp_path / "lab"
    service.init_workspace(workspace_dir)

    report = service.doctor_workspace(workspace_dir)

    token_check = next(check for check in report.checks if check.name == "token_file")
    assert token_check.status == "error"


def test_doctor_reports_missing_runtime_after_uninstall(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    service = _service(tmp_path, FakeDNSProvider())
    service.uninstall_workspace(workspace_dir)

    report = service.doctor_workspace(workspace_dir)

    runtime_check = next(check for check in report.checks if check.name == "runtime_dir")
    logs_check = next(check for check in report.checks if check.name == "runtime_logs_dir")
    assert runtime_check.status == "warn"
    assert logs_check.status == "warn"


def test_uninstall_removes_runtime_and_rendered_but_keeps_workspace_state(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
    )
    provider = FakeDNSProvider()
    service, systemd_manager = _service_with_manager(tmp_path, provider)
    service.render_workspace(workspace_dir)
    service.plan_workspace(workspace_dir)
    service.apply_workspace(workspace_dir, run_sync=False)

    report = service.uninstall_workspace(workspace_dir)

    assert report.purged is False
    assert report.service_stopped is True
    assert report.timer_stopped is True
    assert report.timer_disabled is True
    assert (workspace_dir / "rendered").exists() is False
    assert (workspace_dir / "runtime").exists() is False
    assert (workspace_dir / "workspace.yaml").exists() is True
    assert (workspace_dir / "entries.yaml").exists() is True
    assert (workspace_dir / "secrets").exists() is True
    assert (workspace_dir / "state").exists() is True
    assert report.manual_cleanup_hint == f"rm -rf {workspace_dir.resolve()}"
    assert report.service_reset_failed is True
    assert report.timer_reset_failed is True
    assert ("arbor-ddns-lab", "service") in systemd_manager.reset_failed_units
    assert ("arbor-ddns-lab", "timer") in systemd_manager.reset_failed_units
    assert provider.applied_actions == []


def test_uninstall_purge_removes_workspace(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    service = _service(tmp_path, FakeDNSProvider())

    report = service.uninstall_workspace(workspace_dir, purge=True)

    assert report.purged is True
    assert workspace_dir.exists() is False


def test_apply_preserves_unmanaged_records_and_prunes_only_tracked_stale_records(
    tmp_path: Path,
) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        workspace_dir,
        name="dual",
        source_kind="lxc",
        source_id=101,
        fqdn="dual.example.com",
        family="both",
    )
    discovery_backend = FakeDiscoveryBackend(
        [
            AddressCandidate(
                family=IPAddressFamily.IPV4,
                interface="eth0",
                address="93.184.216.34",
                prefix_length=32,
                source="fake_discovery",
            ),
            AddressCandidate(
                family=IPAddressFamily.IPV6,
                interface="eth0",
                address="2408:8266:5003:506a::88",
                prefix_length=128,
                source="fake_discovery",
            ),
        ]
    )
    unmanaged_record = DNSRecord(
        provider="cloudflare",
        fqdn="keep.example.com",
        record_type="AAAA",
        value="2408:8266:5003:506a::999",
        ttl=120,
        proxied=False,
        record_id="unmanaged-1",
    )
    provider = FakeDNSProvider(initial_records=[unmanaged_record])
    service = _service(tmp_path, provider, discovery_backend=discovery_backend)

    service.sync_once(workspace_dir, apply=True, prune_managed=False)
    EntryService().remove_entry(workspace_dir, name="dual")
    report = service.sync_once(workspace_dir, apply=True, prune_managed=True)

    assert len(report.prune_outcomes) == 2
    assert provider.list_records("keep.example.com", "AAAA")[0].record_id == "unmanaged-1"
