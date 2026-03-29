from __future__ import annotations

from arbor_ddns.config import AppConfig
from arbor_ddns.discovery.base import DiscoveryBackend
from arbor_ddns.discovery.models import AddressCandidate, DiscoveryResult
from arbor_ddns.dns.base import DNSProvider
from arbor_ddns.dns.models import DNSRecord, PlannedChange
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.sync.runner import SyncRunner


class FakeDiscoveryBackend(DiscoveryBackend):
    name = "fake_discovery"

    def discover(self, target: TargetRef) -> DiscoveryResult:
        return DiscoveryResult(
            target=target,
            backend=self.name,
            candidates=[
                AddressCandidate(
                    interface="eth0",
                    address="2408:8266:5003:506a::3d6",
                    prefix_length=128,
                    source=self.name,
                )
            ],
        )


class FakeDNSProvider(DNSProvider):
    name = "cloudflare"

    def __init__(self) -> None:
        self.applied_actions: list[str] = []

    def list_records(self, fqdn: str, record_type: str = "AAAA") -> list[DNSRecord]:
        del fqdn, record_type
        return []

    def apply_change(self, change: PlannedChange) -> DNSRecord | None:
        self.applied_actions.append(change.action)
        return None


def test_runner_plans_and_applies_sync() -> None:
    config = AppConfig.from_mapping(
        {
            "inventory": {
                "entries": [
                    {
                        "kind": "lxc",
                        "id": 101,
                        "fqdn": "host.example.com",
                        "provider": "cloudflare",
                        "selection_policy": "default",
                        "enabled": True,
                    }
                ]
            }
        }
    )
    provider = FakeDNSProvider()
    runner = SyncRunner(
        config=config,
        discovery_backends={
            TargetKind.LXC.value: FakeDiscoveryBackend(),
            TargetKind.VM.value: FakeDiscoveryBackend(),
        },
        provider_factory=lambda provider_name: provider,
    )

    plan_report = runner.plan_inventory()
    apply_report = runner.sync_once(apply=True)

    assert len(plan_report.outcomes) == 1
    assert plan_report.outcomes[0].plan is not None
    assert [change.action for change in plan_report.outcomes[0].plan.changes] == ["create"]
    assert len(apply_report.outcomes) == 1
    assert apply_report.outcomes[0].applied is True
    assert provider.applied_actions == ["create"]

