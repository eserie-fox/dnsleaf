from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from tests.fakes import FakeDiscoveryBackend, FakeDNSProvider

from arbor_ddns.config import OutsideWorkspaceConfig
from arbor_ddns.discovery.local_ip import LocalIPDiscoveryBackend
from arbor_ddns.discovery.models import AddressCandidate
from arbor_ddns.discovery.pve_lxc import PVELXCDiscoveryBackend
from arbor_ddns.discovery.pve_qga import PVEQGADiscoveryBackend
from arbor_ddns.dns.models import DNSRecord
from arbor_ddns.models import IPAddressFamily, TargetKind
from arbor_ddns.sync.runner import SyncRunner
from arbor_ddns.workspace.models import ManagedRecordFile
from arbor_ddns.workspace.storage import WorkspaceStorage


def _prepare_loaded_workspace(tmp_path: Path, entries_yaml: str):
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    storage = WorkspaceStorage()
    (workspace_dir / "entries.yaml").write_text(entries_yaml, encoding="utf-8")
    return storage.validate(workspace_dir), storage


def _build_runner(
    provider: FakeDNSProvider,
    *,
    discovery_backend: FakeDiscoveryBackend | None = None,
    outside_workspace_config: OutsideWorkspaceConfig | None = None,
) -> SyncRunner:
    backend = discovery_backend or FakeDiscoveryBackend()
    return SyncRunner(
        outside_workspace_config=outside_workspace_config,
        discovery_backends={
            TargetKind.LXC.value: backend,
            TargetKind.VM.value: backend,
        },
        provider_factory=lambda loaded: provider,
    )


def test_runner_dry_run_does_not_apply_changes(tmp_path: Path) -> None:
    loaded, _storage = _prepare_loaded_workspace(
        tmp_path,
        (
            "config_version: 2\n"
            "entries:\n"
            "  - name: web\n"
            "    source_kind: lxc\n"
            "    source_id: 101\n"
            "    fqdn: host.example.com\n"
            "    family: ipv6\n"
            "    selection_policy: default\n"
            "    enabled: true\n"
        ),
    )
    provider = FakeDNSProvider()
    runner = _build_runner(provider)

    report = runner.run(
        loaded,
        managed_state=ManagedRecordFile(),
        apply=False,
        prune_managed=False,
    )

    assert len(report.record_outcomes) == 1
    assert report.record_outcomes[0].plan is not None
    assert [change.action for change in report.record_outcomes[0].plan.changes] == ["create"]
    assert provider.applied_actions == []


def test_runner_apply_calls_provider_for_static_both_entry(tmp_path: Path) -> None:
    loaded, _storage = _prepare_loaded_workspace(
        tmp_path,
        (
            "config_version: 2\n"
            "entries:\n"
            "  - name: edge\n"
            "    source_kind: static\n"
            "    fqdn: edge.example.com\n"
            "    family: both\n"
            "    static_ipv4: 93.184.216.34\n"
            "    static_ipv6: 2408:8266:5003:506a::88\n"
            "    enabled: true\n"
        ),
    )
    provider = FakeDNSProvider()
    runner = _build_runner(provider)

    report = runner.run(
        loaded,
        managed_state=ManagedRecordFile(),
        apply=True,
        prune_managed=False,
    )

    assert len(report.record_outcomes) == 2
    assert {outcome.record_type for outcome in report.record_outcomes} == {"A", "AAAA"}
    assert all(outcome.applied for outcome in report.record_outcomes)
    assert provider.applied_actions == ["create", "create"]


def test_runner_handles_dynamic_both_with_one_family_ambiguous(tmp_path: Path) -> None:
    loaded, _storage = _prepare_loaded_workspace(
        tmp_path,
        (
            "config_version: 2\n"
            "entries:\n"
            "  - name: dual\n"
            "    source_kind: lxc\n"
            "    source_id: 101\n"
            "    fqdn: dual.example.com\n"
            "    family: both\n"
            "    selection_policy: default\n"
            "    enabled: true\n"
        ),
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
                address="2408:8266:5003:506a:e27f:4076:f737:e75a",
                prefix_length=64,
                source="fake_discovery",
            ),
            AddressCandidate(
                family=IPAddressFamily.IPV6,
                interface="eth0",
                address="2408:8266:5003:506a:9d54:1c94:fbb1:b5ee",
                prefix_length=64,
                source="fake_discovery",
            ),
        ]
    )
    provider = FakeDNSProvider()
    runner = _build_runner(provider, discovery_backend=discovery_backend)

    report = runner.run(
        loaded,
        managed_state=ManagedRecordFile(),
        apply=False,
        prune_managed=False,
    )

    assert len(report.record_outcomes) == 2
    outcomes_by_type = {outcome.record_type: outcome for outcome in report.record_outcomes}
    assert outcomes_by_type["A"].status == "planned"
    assert outcomes_by_type["AAAA"].status == "skipped"
    assert "none can be preferred safely" in outcomes_by_type["AAAA"].message


def test_runner_plans_prune_for_tracked_stale_record(tmp_path: Path) -> None:
    loaded, _storage = _prepare_loaded_workspace(
        tmp_path,
        (
            "config_version: 2\n"
            "entries:\n"
            "  - name: web\n"
            "    source_kind: lxc\n"
            "    source_id: 101\n"
            "    fqdn: host.example.com\n"
            "    family: ipv6\n"
            "    selection_policy: default\n"
            "    enabled: true\n"
        ),
    )
    stale_record = DNSRecord(
        provider="cloudflare",
        fqdn="old.example.com",
        record_type="AAAA",
        value="2408:8266:5003:506a::88",
        ttl=120,
        proxied=False,
        record_id="rec-stale",
    )
    provider = FakeDNSProvider(initial_records=[stale_record])
    runner = _build_runner(provider)
    managed_state = ManagedRecordFile.model_validate(
        {
            "records": [
                {
                    "workspace_name": "lab",
                    "entry_name": "removed",
                    "fqdn": "old.example.com",
                    "record_type": "AAAA",
                    "record_id": "rec-stale",
                    "value": "2408:8266:5003:506a::88",
                    "ttl": 120,
                    "proxied": False,
                    "state": "stale",
                    "first_managed_at": "2026-01-01T00:00:00+00:00",
                    "last_seen_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        }
    )

    report = runner.run(loaded, managed_state=managed_state, apply=False, prune_managed=True)

    assert len(report.prune_outcomes) == 1
    assert report.prune_outcomes[0].plan is not None
    assert [change.action for change in report.prune_outcomes[0].plan.changes] == ["delete"]


def test_runner_uses_outside_workspace_paths_for_discovery_fallback() -> None:
    runner = SyncRunner(
        outside_workspace_config=OutsideWorkspaceConfig.from_mapping(
            {
                "paths": {
                    "pct_bin": "/usr/sbin/pct",
                    "qm_bin": "/usr/sbin/qm",
                    "shell_bin": "/bin/bash",
                },
                "arbor_ddns_logging": {
                    "level": "INFO",
                    "format": "%(message)s",
                    "file_path": None,
                    "retention_days": 7,
                    "stream": "stderr",
                },
            }
        ),
        provider_factory=lambda loaded: FakeDNSProvider(),
    )

    lxc_backend = runner._backend_for_kind(TargetKind.LXC, loaded_workspace=None)
    local_backend = runner._backend_for_kind(TargetKind.LOCAL, loaded_workspace=None)
    vm_backend = runner._backend_for_kind(TargetKind.VM, loaded_workspace=None)

    assert isinstance(lxc_backend, PVELXCDiscoveryBackend)
    assert lxc_backend._pct_bin == "/usr/sbin/pct"
    assert lxc_backend._shell_bin == "/bin/bash"
    assert isinstance(local_backend, LocalIPDiscoveryBackend)
    assert isinstance(vm_backend, PVEQGADiscoveryBackend)
    assert vm_backend._qm_bin == "/usr/sbin/qm"


def test_runner_preserves_remote_proxy_state_when_proxy_is_unmanaged(tmp_path: Path) -> None:
    loaded, storage = _prepare_loaded_workspace(
        tmp_path,
        (
            "config_version: 2\n"
            "entries:\n"
            "  - name: web\n"
            "    source_kind: lxc\n"
            "    source_id: 101\n"
            "    fqdn: host.example.com\n"
            "    family: ipv6\n"
            "    selection_policy: default\n"
            "    enabled: true\n"
        ),
    )
    workspace_yaml = yaml.safe_load((loaded.paths.workspace_file).read_text(encoding="utf-8"))
    workspace_yaml["default_ttl"] = 300
    workspace_yaml["default_proxied"] = None
    loaded.paths.workspace_file.write_text(
        yaml.safe_dump(workspace_yaml, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    loaded = storage.validate(loaded.paths.root)

    current_record = DNSRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="AAAA",
        value="2408:8266:5003:506a::3d6",
        ttl=1,
        proxied=True,
        record_id="rec-1",
    )
    provider = FakeDNSProvider(initial_records=[current_record])
    runner = _build_runner(provider)

    report = runner.run(
        loaded,
        managed_state=ManagedRecordFile(),
        apply=False,
        prune_managed=False,
    )

    assert len(report.record_outcomes) == 1
    assert report.record_outcomes[0].plan is not None
    assert [change.action for change in report.record_outcomes[0].plan.changes] == ["noop"]
