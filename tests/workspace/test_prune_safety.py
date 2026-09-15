from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dnsleaf.discovery.models import AddressCandidate, DiscoveryResult
from dnsleaf.dns.models import DNSRecord
from dnsleaf.models import IPAddressFamily, TargetKind
from dnsleaf.sync.runner import SyncRunner, WorkspaceRunReport
from dnsleaf.workspace.entries import EntryService
from dnsleaf.workspace.service import WorkspaceService
from dnsleaf.workspace.state import load_managed_records, write_managed_records
from dnsleaf.workspace.storage import WorkspaceStorage, dump_yaml_data
from tests.fakes import FakeDiscoveryBackend, FakeDNSProvider


def _setup(
    workspace: Path, *, family: str = "ipv4", dynamic: bool = False
) -> tuple[WorkspaceService, FakeDNSProvider, FakeDiscoveryBackend]:
    EntryService().add_entry(
        workspace,
        name="web",
        source_kind="lxc" if dynamic else "static",
        source_id=101 if dynamic else None,
        fqdn="host.example.com",
        family=family,
        static_ipv4=None if dynamic else "93.184.216.34",
        static_ipv6="2001:4860::88" if family == "both" else None,
    )
    provider = FakeDNSProvider(
        [
            DNSRecord(
                provider="cloudflare",
                fqdn="untracked.example.com",
                record_type="A",
                value="93.184.216.35",
                ttl=300,
                record_id="untracked",
            )
        ]
    )
    backend = FakeDiscoveryBackend()
    service = WorkspaceService(
        runner=SyncRunner(
            provider_factory=lambda loaded: provider,
            discovery_backends={TargetKind.LXC.value: backend},
        )
    )
    assert not service.sync_once(workspace, apply=True).has_errors()
    provider.applied_actions.clear()
    return service, provider, backend


def _edit_entry(workspace: Path, **changes) -> None:
    path = workspace / "entries.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["entries"][0].update(changes)
    dump_yaml_data(path, data)


def _mark_stale(workspace: Path, service: WorkspaceService) -> None:
    _edit_entry(workspace, enabled=False)
    assert not service.sync_once(workspace, apply=True, prune_managed=False).has_errors()
    state = load_managed_records(WorkspaceStorage().paths_for(workspace))
    assert all(record.state == "stale" for record in state.records)


def _assert_no_delete_plans(report: WorkspaceRunReport) -> None:
    plans = [outcome.plan for outcome in report.record_outcomes] + [
        outcome.plan for outcome in report.prune_outcomes
    ]
    for plan in plans:
        if plan is not None:
            assert all(change.action != "delete" for change in plan.changes)
    assert report.prune_outcomes == []


@pytest.mark.parametrize("change", ["reenable", "rename", "rename-and-update"])
@pytest.mark.parametrize("apply", [False, True], ids=["plan", "apply"])
def test_desired_target_survives_entry_recovery(workspace_dir: Path, change: str, apply: bool):
    service, provider, _ = _setup(workspace_dir)
    paths = WorkspaceStorage().paths_for(workspace_dir)
    original = load_managed_records(paths).records[0]
    if change == "reenable":
        _mark_stale(workspace_dir, service)
        _edit_entry(workspace_dir, enabled=True)
        name = "web"
    else:
        _edit_entry(workspace_dir, name="frontend")
        name = "frontend"
        if change == "rename-and-update":
            _edit_entry(workspace_dir, static_ipv4="93.184.216.36")
    before = paths.managed_records_file.read_bytes()

    report = (
        service.sync_once(workspace_dir, apply=True, prune_managed=True)
        if apply
        else service.plan_workspace(workspace_dir, prune_managed=True)
    )
    assert "delete" not in provider.applied_actions
    _assert_no_delete_plans(report)
    assert not report.has_errors()
    assert [r.record_id for r in provider.list_records("host.example.com", "A")] == [
        original.record_id
    ]
    if not apply:
        assert provider.applied_actions == []
        assert paths.managed_records_file.read_bytes() == before
        return

    for _ in range(2):
        state = load_managed_records(paths)
        assert len(state.records) == 1
        record = state.records[0]
        assert (record.entry_name, record.record_id, record.state) == (
            name,
            original.record_id,
            "active",
        )
        assert record.first_managed_at == original.first_managed_at
        provider.applied_actions.clear()
        report = service.sync_once(workspace_dir, apply=True, prune_managed=True)
        _assert_no_delete_plans(report)
        assert not report.has_errors()
        assert provider.applied_actions == []
        assert provider.list_records("host.example.com", "A")[0].record_id == original.record_id


@pytest.mark.parametrize("discovery", ["unavailable", "ambiguous", "failed"])
def test_stale_desired_target_is_protected_without_selected_address(
    workspace_dir: Path, monkeypatch, discovery: str
):
    service, provider, backend = _setup(workspace_dir, dynamic=True)
    paths = WorkspaceStorage().paths_for(workspace_dir)
    original = load_managed_records(paths).records[0]
    _mark_stale(workspace_dir, service)
    _edit_entry(workspace_dir, enabled=True, name="frontend")
    candidates = (
        [
            AddressCandidate(
                family=IPAddressFamily.IPV4,
                interface="eth0",
                address=address,
                prefix_length=32,
                source="test",
            )
            for address in ("93.184.216.34", "93.184.216.35")
        ]
        if discovery == "ambiguous"
        else []
    )
    monkeypatch.setattr(
        backend,
        "discover",
        lambda target: DiscoveryResult(
            target=target,
            backend=backend.name,
            candidates=candidates,
            error="test discovery failure" if discovery == "failed" else None,
        ),
    )
    before = paths.managed_records_file.read_bytes()
    plan = service.plan_workspace(workspace_dir, prune_managed=True)
    _assert_no_delete_plans(plan)
    assert plan.record_outcomes[0].selected_value is None
    assert paths.managed_records_file.read_bytes() == before

    for _ in range(2):
        report = service.sync_once(workspace_dir, apply=True, prune_managed=True)
        assert provider.applied_actions == []
        _assert_no_delete_plans(report)
        assert report.record_outcomes[0].selected_value is None
        records = load_managed_records(paths).records
        assert len(records) == 1
        assert (records[0].entry_name, records[0].record_id, records[0].state) == (
            "frontend",
            original.record_id,
            "active",
        )
        assert records[0].first_managed_at == original.first_managed_at
        assert provider.list_records("host.example.com", "A")[0].record_id == original.record_id


@pytest.mark.parametrize("fqdn", ["host.example.com", "HOST.Example.COM."])
def test_normalized_targets_and_duplicate_ownership_are_reconciled(
    workspace_dir: Path, monkeypatch, fqdn: str
):
    service, provider, _ = _setup(workspace_dir)
    paths = WorkspaceStorage().paths_for(workspace_dir)
    state = load_managed_records(paths)
    original = state.records[0].model_copy()
    state.records.append(
        original.model_copy(
            update={
                "entry_name": "old-label",
                "fqdn": "HOST.Example.COM.",
                "record_type": "a",
                "state": "stale",
            }
        )
    )
    write_managed_records(paths, state)
    _edit_entry(workspace_dir, name="frontend", fqdn=fqdn)
    list_records = provider.list_records
    monkeypatch.setattr(
        provider,
        "list_records",
        lambda name, record_type=None: list_records(name.rstrip(".").lower(), record_type),
    )
    _assert_no_delete_plans(service.plan_workspace(workspace_dir, prune_managed=True))
    for _ in range(2):
        report = service.sync_once(workspace_dir, apply=True, prune_managed=True)
        _assert_no_delete_plans(report)
        assert provider.applied_actions == []
        records = load_managed_records(paths).records
        assert len(records) == 1
        assert records[0].entry_name == "frontend"
        assert records[0].record_id == original.record_id
        assert records[0].state == "active"


def test_desired_target_is_protected_when_provider_planning_fails(workspace_dir: Path, monkeypatch):
    service, provider, _ = _setup(workspace_dir)
    paths = WorkspaceStorage().paths_for(workspace_dir)
    original = load_managed_records(paths).records[0]
    _mark_stale(workspace_dir, service)
    _edit_entry(workspace_dir, enabled=True, name="frontend")
    original_records = provider.list_records("host.example.com")

    def failed_listing(*args, **kwargs):
        raise RuntimeError("test provider listing failure")

    with monkeypatch.context() as patch:
        patch.setattr(provider, "list_records", failed_listing)
        before = paths.managed_records_file.read_bytes()
        plan = service.plan_workspace(workspace_dir, prune_managed=True)
        assert plan.has_errors()
        _assert_no_delete_plans(plan)
        assert paths.managed_records_file.read_bytes() == before
        report = service.sync_once(workspace_dir, apply=True, prune_managed=True)
        assert report.has_errors()
        _assert_no_delete_plans(report)
        assert provider.applied_actions == []

    records = load_managed_records(paths).records
    assert len(records) == 1
    assert (records[0].entry_name, records[0].record_id, records[0].state) == (
        "frontend",
        original.record_id,
        "active",
    )
    assert provider.list_records("host.example.com") == original_records


@pytest.mark.parametrize("retire", ["all", "ipv6"])
def test_prune_retires_only_no_longer_desired_tracked_targets(workspace_dir: Path, retire: str):
    service, provider, _ = _setup(workspace_dir, family="both")
    paths = WorkspaceStorage().paths_for(workspace_dir)
    original = {r.record_type: r for r in load_managed_records(paths).records}
    untracked = provider.list_records("untracked.example.com")
    if retire == "all":
        EntryService().remove_entry(workspace_dir, name="web")
        retired_types = {"A", "AAAA"}
    else:
        _mark_stale(workspace_dir, service)
        _edit_entry(workspace_dir, enabled=True, name="frontend", family="ipv4", static_ipv6=None)
        retired_types = {"AAAA"}
    before = paths.managed_records_file.read_bytes()
    plan = service.plan_workspace(workspace_dir, prune_managed=True)
    assert {outcome.record_type for outcome in plan.prune_outcomes} == retired_types
    assert provider.applied_actions == []
    assert paths.managed_records_file.read_bytes() == before
    report = service.sync_once(workspace_dir, apply=True, prune_managed=True)
    assert not report.has_errors()
    assert provider.applied_actions == ["delete"] * len(retired_types)
    assert all(outcome.applied for outcome in report.prune_outcomes)
    assert provider.list_records("untracked.example.com") == untracked
    assert provider.list_records("host.example.com", "AAAA") == []
    records = load_managed_records(paths).records
    if retire == "all":
        assert records == []
        assert provider.list_records("host.example.com") == []
    else:
        assert len(records) == 1
        assert (records[0].entry_name, records[0].record_type, records[0].state) == (
            "frontend",
            "A",
            "active",
        )
        assert records[0].record_id == original["A"].record_id
        assert (
            provider.list_records("host.example.com", "A")[0].record_id == original["A"].record_id
        )
