from __future__ import annotations

from typer.testing import CliRunner

from arbor_ddns import cli
from arbor_ddns.discovery.models import AddressCandidate, DiscoveryResult, SelectionResult
from arbor_ddns.dns.models import DesiredRecord, PlannedChange, SyncPlan
from arbor_ddns.models import InventoryEntry, SelectedAddress, TargetKind, TargetRef
from arbor_ddns.sync.runner import EntrySyncOutcome, RunReport

runner = CliRunner()


class FakeRunner:
    def discover_target(
        self,
        target: TargetRef,
        *,
        policy: str = "default",
    ) -> tuple[DiscoveryResult, SelectionResult]:
        del policy
        discovery = DiscoveryResult(
            target=target,
            backend="fake",
            candidates=[
                AddressCandidate(
                    interface="eth0",
                    address="2408:8266:5003:506a::3d6",
                    prefix_length=128,
                    source="fake",
                )
            ],
        )
        selection = SelectionResult(
            target=target,
            policy="default",
            status="selected",
            selected=SelectedAddress(
                target=target,
                address="2408:8266:5003:506a::3d6",
                prefix_length=128,
                interface="eth0",
                selection_policy="default",
                source="fake",
                reason="preferred explicit /128 candidate",
            ),
            remaining_candidates=discovery.candidates,
            filtered_out=[],
            not_selected=[],
            reason="preferred explicit /128 candidate",
        )
        return discovery, selection

    def plan_inventory(self) -> RunReport:
        entry = InventoryEntry(
            kind=TargetKind.LXC,
            id=101,
            fqdn="host.example.com",
            provider="cloudflare",
            selection_policy="default",
            enabled=True,
        )
        target = entry.to_target_ref()
        discovery, selection = self.discover_target(target)
        plan = SyncPlan(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            desired=DesiredRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                value="2408:8266:5003:506a::3d6",
                ttl=300,
            ),
            changes=[
                PlannedChange(
                    action="create",
                    provider="cloudflare",
                    fqdn="host.example.com",
                    record_type="AAAA",
                    desired=DesiredRecord(
                        provider="cloudflare",
                        fqdn="host.example.com",
                        record_type="AAAA",
                        value="2408:8266:5003:506a::3d6",
                        ttl=300,
                    ),
                    reason="record does not exist yet",
                )
            ],
        )
        return RunReport(
            outcomes=[
                EntrySyncOutcome(
                    entry=entry,
                    discovery=discovery,
                    selection=selection,
                    plan=plan,
                    status="planned",
                    message="changes planned",
                )
            ],
            dry_run=True,
        )

    def sync_once(self, *, apply: bool = False) -> RunReport:
        report = self.plan_inventory()
        report.dry_run = not apply
        return report


def test_discover_lxc_command(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_load_config", lambda config_path: object())
    monkeypatch.setattr(cli, "_build_runner", lambda config: FakeRunner())

    result = runner.invoke(cli.app, ["discover", "lxc", "101"])

    assert result.exit_code == 0
    assert "target=lxc/101" in result.stdout
    assert "selected=2408:8266:5003:506a::3d6/128" in result.stdout


def test_plan_command(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_load_config", lambda config_path: object())
    monkeypatch.setattr(cli, "_build_runner", lambda config: FakeRunner())

    result = runner.invoke(cli.app, ["plan"])

    assert result.exit_code == 0
    assert "Plan" in result.stdout
    assert "change=create" in result.stdout


def test_sync_once_apply_command(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_load_config", lambda config_path: object())
    monkeypatch.setattr(cli, "_build_runner", lambda config: FakeRunner())

    result = runner.invoke(cli.app, ["sync-once", "--apply"])

    assert result.exit_code == 0
    assert "Apply" in result.stdout
