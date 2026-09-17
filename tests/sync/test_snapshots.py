from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from dnsleaf.discovery.base import DiscoveryBackend
from dnsleaf.discovery.models import AddressCandidate, DiscoveryResult
from dnsleaf.discovery.pve_qga import PVEQGADiscoveryBackend
from dnsleaf.models import IPAddressFamily, TargetRef
from dnsleaf.sync.runner import SyncRunner
from dnsleaf.util.process import CommandTimeoutError
from dnsleaf.workspace.models import EntriesFile, ManagedRecordFile, ManagedRecordSnapshot
from dnsleaf.workspace.storage import WorkspaceStorage
from tests.fakes import FakeDNSProvider


def entry(name: str, family: str, source_id: int | None = 101, kind: str = "vm"):
    return dict(
        name=name,
        source_kind=kind,
        source_id=source_id,
        family=family,
        fqdn=f"{name}.example.com",
        enabled=True,
        selection_policy="default",
    )


class ChangingBackend(DiscoveryBackend):
    name = "snapshot-test"

    def __init__(self) -> None:
        self.calls: list[TargetRef] = []

    def discover(self, target: TargetRef) -> DiscoveryResult:
        self.calls.append(target)
        return DiscoveryResult(
            target=target,
            backend=self.name,
            candidates=[
                AddressCandidate(
                    family=IPAddressFamily.IPV4,
                    interface="Ethernet",
                    address="8.8.8.8",
                    prefix_length=32,
                    source=self.name,
                ),
                AddressCandidate(
                    family=IPAddressFamily.IPV6,
                    interface="Ethernet",
                    address=f"2001:4860::{len(self.calls)}",
                    prefix_length=128,
                    source=self.name,
                ),
            ],
        )


@pytest.mark.parametrize("kind,source_id", [("vm", 101), ("local", None)])
def test_raw_snapshot_reused_per_source_and_refreshed_each_run(
    workspace_dir: Path, kind, source_id
):
    loaded = WorkspaceStorage().load(workspace_dir)
    loaded.entries_file = EntriesFile.from_mapping(
        {
            "entries": [
                entry("node", "both", source_id, kind),
                entry("service", "ipv6", source_id, kind),
                entry("other", "ipv4", 102),
            ]
        }
    )
    backend = ChangingBackend()
    provider = FakeDNSProvider()
    runner = SyncRunner(
        provider_factory=lambda _: provider, discovery_backends={"vm": backend, "local": backend}
    )
    first = runner.run(loaded, managed_state=ManagedRecordFile(), apply=False, prune_managed=False)
    assert len(backend.calls) == 2
    node4, node6, service6, other4 = first.record_outcomes
    assert node4.fqdn != service6.fqdn and node4.family != service6.family
    assert node6.selected_value == service6.selected_value == "2001:4860::1"
    assert node4.discovery is node6.discovery is service6.discovery
    assert other4.discovery is not node4.discovery
    assert node4.discovery is not None
    original = node4.discovery.model_dump()
    second = runner.run(loaded, managed_state=ManagedRecordFile(), apply=False, prune_managed=False)
    assert len(backend.calls) == 4
    assert second.record_outcomes[1].selected_value == "2001:4860::3"
    assert node4.discovery.model_dump() == original
    assert provider.applied_actions == []


def test_timed_out_guest_reused_and_other_guest_processed_without_prune(workspace_dir: Path):
    loaded = WorkspaceStorage().load(workspace_dir)
    loaded.entries_file = EntriesFile.from_mapping(
        {
            "entries": [
                entry("node", "ipv6"),
                entry("service", "both"),
                entry("other", "ipv4", 102),
            ]
        }
    )
    calls = []

    def fake(args: Sequence[str], *, check: bool = True, timeout: float | None = None):
        calls.append(tuple(args))
        if args[2] == "101":
            raise CommandTimeoutError(args, timeout)
        from dnsleaf.util.process import CommandResult

        return CommandResult(
            tuple(args),
            0,
            '[{"name":"Ethernet 2","ip-addresses":[{"ip-address":"8.8.8.8",'
            '"ip-address-type":"ipv4","prefix":32}]}]',
            "",
        )

    provider = FakeDNSProvider()
    runner = SyncRunner(
        provider_factory=lambda _: provider,
        discovery_backends={"vm": PVEQGADiscoveryBackend(runner=fake)},
    )
    previous = ManagedRecordFile(
        records=[
            ManagedRecordSnapshot(
                workspace_name="lab",
                entry_name="old",
                fqdn="node.example.com",
                record_type="AAAA",
                value="2001:4860::99",
                ttl=300,
                record_id="owned",
                state="stale",
                first_managed_at="before",
                last_seen_at="before",
            )
        ]
    )
    report = runner.run(loaded, managed_state=previous, apply=True, prune_managed=True)
    assert [call[2] for call in calls] == ["101", "102"]
    assert [o.status for o in report.record_outcomes] == ["error", "error", "error", "planned"]
    assert report.record_outcomes[-1].applied
    assert report.has_errors() and report.prune_outcomes == []
    assert "delete" not in provider.applied_actions
    assert report.record_outcomes[0].discovery is report.record_outcomes[1].discovery
