from __future__ import annotations

from pathlib import Path

import pytest

from dnsleaf.discovery.models import AddressCandidate
from dnsleaf.dns.models import DNSRecord
from dnsleaf.logging.runtime import workspace_logging_context
from dnsleaf.models import IPAddressFamily, TargetKind
from dnsleaf.sync.runner import SyncRunner
from dnsleaf.workspace.entries import EntryService
from dnsleaf.workspace.service import WorkspaceService
from dnsleaf.workspace.state import load_last_apply, load_managed_records
from dnsleaf.workspace.storage import WorkspaceStorage
from tests.fakes import FakeDiscoveryBackend, FakeDNSProvider, FakeSystemdManager


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
        "dnsleaf.workspace.service.CloudflareDNSProvider",
        lambda config: FakeDNSProvider(),
    )

    verification = service.provider_verify(WorkspaceStorage().load(workspace_dir))

    assert verification.provider == "cloudflare"
    assert verification.zone_id == "zone-123"


def test_sync_once_updates_managed_record_state_and_prunes_safely(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    entries = EntryService()
    entries.add_entry(
        WorkspaceStorage().load(workspace_dir),
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
    )

    provider = FakeDNSProvider()
    service = _service(tmp_path, provider)

    first_report = service.sync_once(
        WorkspaceStorage().load(workspace_dir), apply=True, prune_managed=False
    )
    managed_state = load_managed_records(service._storage.paths_for(workspace_dir))

    assert first_report.record_outcomes[0].applied is True
    assert len(managed_state.records) == 1
    assert managed_state.records[0].state == "active"

    EntryService().remove_entry(WorkspaceStorage().load(workspace_dir), name="web")
    second_report = service.sync_once(
        WorkspaceStorage().load(workspace_dir), apply=True, prune_managed=False
    )
    managed_state = load_managed_records(service._storage.paths_for(workspace_dir))

    assert second_report.record_outcomes == []
    assert len(managed_state.records) == 1
    assert managed_state.records[0].state == "stale"

    third_report = service.sync_once(
        WorkspaceStorage().load(workspace_dir), apply=True, prune_managed=True
    )
    managed_state = load_managed_records(service._storage.paths_for(workspace_dir))

    assert third_report.prune_outcomes[0].status == "applied"
    assert managed_state.records == []


def test_apply_renders_installs_units_and_records_last_apply(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        WorkspaceStorage().load(workspace_dir),
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
    )
    provider = FakeDNSProvider()
    service = _service(tmp_path, provider)

    report = service.apply_workspace(WorkspaceStorage().load(workspace_dir), run_sync=True)
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
        WorkspaceStorage().load(workspace_dir),
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
        service.plan_workspace(WorkspaceStorage().load(workspace_dir))

    log_file = workspace_dir / "runtime" / "logs" / "dnsleaf.log"
    log_content = log_file.resolve().read_text(encoding="utf-8")
    assert log_file.is_symlink()
    assert "command=plan" in log_content
    assert "entry=web" in log_content
    assert "secret-token" not in log_content


def test_status_aggregates_state_and_systemd(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        WorkspaceStorage().load(workspace_dir),
        name="edge",
        source_kind="static",
        fqdn="edge.example.com",
        family="both",
        static_ipv4="93.184.216.34",
        static_ipv6="2001:4860:abcd:1234::88",
    )
    service = _service(tmp_path, FakeDNSProvider())
    service.render_workspace(WorkspaceStorage().load(workspace_dir))
    service.apply_workspace(WorkspaceStorage().load(workspace_dir), run_sync=False)

    status = service.status_workspace(workspace_dir)

    assert status.workspace_name == "lab"
    assert status.entry_count == 1
    assert status.rendered_artifacts["effective_workspace"] is True
    assert status.runtime_dir_exists is True
    assert status.runtime_log_file is not None
    assert status.runtime_log_file.endswith("runtime/logs/dnsleaf.log")
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
    service.uninstall_workspace(WorkspaceStorage().load(workspace_dir))

    report = service.doctor_workspace(workspace_dir)

    runtime_check = next(check for check in report.checks if check.name == "runtime_dir")
    logs_check = next(check for check in report.checks if check.name == "runtime_logs_dir")
    assert runtime_check.status == "warn"
    assert logs_check.status == "warn"


def test_uninstall_removes_runtime_and_rendered_but_keeps_workspace_state(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        WorkspaceStorage().load(workspace_dir),
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
    )
    provider = FakeDNSProvider()
    service, systemd_manager = _service_with_manager(tmp_path, provider)
    service.render_workspace(WorkspaceStorage().load(workspace_dir))
    service.plan_workspace(WorkspaceStorage().load(workspace_dir))
    service.apply_workspace(WorkspaceStorage().load(workspace_dir), run_sync=False)

    report = service.uninstall_workspace(WorkspaceStorage().load(workspace_dir))

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
    assert report.manual_cleanup_hint == f"rm -rf -- {workspace_dir.resolve()}"
    assert report.service_reset_failed is True
    assert report.timer_reset_failed is True
    assert ("dnsleaf-lab", "service") in systemd_manager.reset_failed_units
    assert ("dnsleaf-lab", "timer") in systemd_manager.reset_failed_units
    assert provider.applied_actions == []


def test_uninstall_purge_removes_workspace(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    service = _service(tmp_path, FakeDNSProvider())

    report = service.uninstall_workspace(WorkspaceStorage().load(workspace_dir), purge=True)

    assert report.purged is True
    assert workspace_dir.exists() is False


def test_apply_preserves_unmanaged_records_and_prunes_only_tracked_stale_records(
    tmp_path: Path,
) -> None:
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        WorkspaceStorage().load(workspace_dir),
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
                address="2001:4860:abcd:1234::88",
                prefix_length=128,
                source="fake_discovery",
            ),
        ]
    )
    unmanaged_record = DNSRecord(
        provider="cloudflare",
        fqdn="keep.example.com",
        record_type="AAAA",
        value="2001:4860:abcd:1234::999",
        ttl=120,
        proxied=False,
        record_id="unmanaged-1",
    )
    provider = FakeDNSProvider(initial_records=[unmanaged_record])
    service = _service(tmp_path, provider, discovery_backend=discovery_backend)

    service.sync_once(WorkspaceStorage().load(workspace_dir), apply=True, prune_managed=False)
    EntryService().remove_entry(WorkspaceStorage().load(workspace_dir), name="dual")
    report = service.sync_once(
        WorkspaceStorage().load(workspace_dir), apply=True, prune_managed=True
    )

    assert len(report.prune_outcomes) == 2
    assert provider.list_records("keep.example.com", "AAAA")[0].record_id == "unmanaged-1"


def test_uninstall_stops_timer_before_service(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    service, manager = _service_with_manager(tmp_path, FakeDNSProvider())
    service.uninstall_workspace(WorkspaceStorage().load(workspace))
    assert manager.calls[:3] == ["stop_timer", "stop_service", "disable_timer"]


@pytest.mark.parametrize("failed_action", ["stop_timer", "stop_service", "disable_timer"])
def test_failed_uninstall_preserves_workspace_and_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_action: str,
) -> None:
    from dnsleaf.systemd import SystemdError
    from dnsleaf.util.process import CommandResult
    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    provider = FakeDNSProvider()
    service, manager = _service_with_manager(tmp_path, provider)
    service.apply_workspace(WorkspaceStorage().load(workspace), run_sync=False)
    monkeypatch.setattr(
        manager,
        failed_action,
        lambda *args, **kwargs: CommandResult(
            args=("systemctl", failed_action),
            returncode=1,
            stdout="",
            stderr="Access denied",
        ),
    )
    with pytest.raises(SystemdError, match="Access denied"):
        service.uninstall_workspace(WorkspaceStorage().load(workspace), purge=True)
    assert (workspace / "workspace.yaml").exists()
    assert (workspace / "runtime").exists()
    assert (workspace / "state").exists()
    assert (manager.unit_dir / "dnsleaf-lab.service").exists()
    assert provider.applied_actions == []


def test_sync_checks_state_writability_before_remote_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    provider = FakeDNSProvider()
    service = _service(tmp_path, provider)

    def denied(path: Path) -> None:
        raise PermissionError("state is read-only")

    monkeypatch.setattr("dnsleaf.workspace.service.ensure_writable_directory", denied)
    with pytest.raises(PermissionError, match="state is read-only"):
        service.sync_once(WorkspaceStorage().load(workspace), apply=True)
    assert provider.applied_actions == []


def test_sync_preserves_duplicate_remote_records_without_prune(tmp_path: Path) -> None:
    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    EntryService().add_entry(
        WorkspaceStorage().load(workspace),
        name="edge",
        source_kind="static",
        family="ipv4",
        fqdn="edge.example.com",
        static_ipv4="192.0.2.1",
    )
    records = [
        DNSRecord(
            provider="cloudflare",
            fqdn="edge.example.com",
            record_type="A",
            value=f"192.0.2.{index}",
            ttl=1,
            record_id=f"record-{index}",
        )
        for index in [1, 2]
    ]
    provider = FakeDNSProvider(records)
    report = _service(tmp_path, provider).sync_once(WorkspaceStorage().load(workspace), apply=True)
    assert report.has_errors()
    assert "refusing to choose or delete" in report.record_outcomes[0].message
    assert provider.applied_actions == []
    assert provider.list_records("edge.example.com", "A") == records


def test_uninstall_refuses_external_generated_directory_symlink(tmp_path: Path) -> None:
    import shutil

    from tests.conftest import scaffold_workspace

    workspace = scaffold_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep")
    shutil.rmtree(workspace / "rendered")
    (workspace / "rendered").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside workspace root"):
        _service(tmp_path, FakeDNSProvider()).uninstall_workspace(
            WorkspaceStorage().load(workspace), purge=True
        )
    assert sentinel.read_text() == "keep"
    assert workspace.exists()
