from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeDiscoveryBackend, FakeDNSProvider

from arbor_ddns.config import AppConfig
from arbor_ddns.dns.models import DNSRecord
from arbor_ddns.models import TargetKind
from arbor_ddns.sync.runner import SyncRunner
from arbor_ddns.workspace.models import ManagedRecordFile
from arbor_ddns.workspace.storage import WorkspaceStorage


def _app_config(tmp_path: Path) -> AppConfig:
    return AppConfig.from_mapping(
        {
            "systemd": {
                "unit_dir": str(tmp_path / "units"),
            }
        }
    )


def _prepare_loaded_workspace(tmp_path: Path):
    from tests.conftest import scaffold_workspace

    workspace_dir = scaffold_workspace(tmp_path)
    storage = WorkspaceStorage(_app_config(tmp_path))
    (workspace_dir / "entries.yaml").write_text(
        (
            "config_version: 1\n"
            "entries:\n"
            "  - name: web\n"
            "    source_kind: lxc\n"
            "    source_id: 101\n"
            "    fqdn: host.example.com\n"
            "    record_type: AAAA\n"
            "    selection_policy: default\n"
            "    enabled: true\n"
        ),
        encoding="utf-8",
    )
    return storage.validate(workspace_dir), storage


def _build_runner(tmp_path: Path, provider: FakeDNSProvider) -> SyncRunner:
    app_config = _app_config(tmp_path)
    return SyncRunner(
        app_config=app_config,
        discovery_backends={
            TargetKind.LXC.value: FakeDiscoveryBackend(),
            TargetKind.VM.value: FakeDiscoveryBackend(),
        },
        provider_factory=lambda loaded: provider,
    )


def test_runner_dry_run_does_not_apply_changes(tmp_path: Path) -> None:
    loaded, _storage = _prepare_loaded_workspace(tmp_path)
    provider = FakeDNSProvider()
    runner = _build_runner(tmp_path, provider)

    report = runner.run(
        loaded,
        managed_state=ManagedRecordFile(),
        apply=False,
        prune_managed=False,
    )

    assert len(report.entry_outcomes) == 1
    assert report.entry_outcomes[0].plan is not None
    assert [change.action for change in report.entry_outcomes[0].plan.changes] == ["create"]
    assert provider.applied_actions == []


def test_runner_apply_calls_provider(tmp_path: Path) -> None:
    loaded, _storage = _prepare_loaded_workspace(tmp_path)
    provider = FakeDNSProvider()
    runner = _build_runner(tmp_path, provider)

    report = runner.run(
        loaded,
        managed_state=ManagedRecordFile(),
        apply=True,
        prune_managed=False,
    )

    assert len(report.entry_outcomes) == 1
    assert report.entry_outcomes[0].applied is True
    assert report.entry_outcomes[0].final_record is not None
    assert provider.applied_actions == ["create"]


def test_runner_plans_prune_for_tracked_stale_record(tmp_path: Path) -> None:
    loaded, _storage = _prepare_loaded_workspace(tmp_path)
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
    runner = _build_runner(tmp_path, provider)
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
