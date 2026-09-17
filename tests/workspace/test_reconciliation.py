from pathlib import Path

from dnsleaf.dns.models import DNSRecord
from dnsleaf.models import EntrySourceKind, IPAddressFamily
from dnsleaf.workspace.models import EntriesFile, ManagedRecordFile, ManagedRecordSnapshot
from dnsleaf.workspace.reports import PruneOutcome, RecordSyncOutcome, WorkspaceRunReport
from dnsleaf.workspace.state import reconcile_managed_state
from dnsleaf.workspace.storage import WorkspaceStorage


def snapshot(name: str, fqdn: str, record_id: str, first: str, last: str):
    return ManagedRecordSnapshot(
        workspace_name="lab",
        entry_name=name,
        fqdn=fqdn,
        record_type="AAAA",
        record_id=record_id,
        value="2001:4860::1",
        ttl=300,
        state="stale",
        first_managed_at=first,
        last_seen_at=last,
    )


def test_reconciliation_explicit_time_alias_cleanup_and_input_immutability(workspace_dir: Path):
    loaded = WorkspaceStorage().load(workspace_dir)
    loaded.entries_file = EntriesFile.from_mapping(
        {
            "entries": [
                dict(
                    name="renamed",
                    source_kind="local",
                    family="ipv6",
                    fqdn="NODE.example.com.",
                    enabled=True,
                    selection_policy="default",
                )
            ]
        }
    )
    previous = ManagedRecordFile(
        records=[
            snapshot("old", "node.example.com", "same", "01", "02"),
            snapshot("older", "NODE.example.com.", "same", "00", "01"),
            snapshot("alias", "alias.example.com", "same", "00", "02"),
            snapshot("gone", "gone.example.com", "gone", "01", "02"),
            snapshot("failed", "failed.example.com", "failed", "01", "02"),
        ]
    )
    before = previous.model_dump()
    report = WorkspaceRunReport(
        workspace_name="lab",
        dry_run=False,
        record_outcomes=[
            RecordSyncOutcome(
                entry_name="renamed",
                source_kind=EntrySourceKind.LOCAL,
                source_id=None,
                family=IPAddressFamily.IPV6,
                fqdn="node.example.com",
                record_type="AAAA",
                value_source="dynamic",
                status="planned",
                message="already in sync",
                final_record=DNSRecord(
                    provider="cloudflare",
                    fqdn="node.example.com",
                    record_type="AAAA",
                    record_id="same",
                    value="2001:4860::2",
                    ttl=300,
                ),
            )
        ],
        prune_outcomes=[
            PruneOutcome(
                entry_name=name,
                fqdn=f"{name}.example.com",
                record_type="AAAA",
                record_id=name,
                value="2001:4860::1",
                status=status,
                message=status,
            )
            for name, status in [("gone", "confirmed_absent"), ("failed", "error")]
        ],
    )
    reconciled = reconcile_managed_state(loaded, previous, report, now="03")
    assert previous.model_dump() == before
    assert {r.record_id for r in reconciled.records} == {"same", "failed"}
    current = next(r for r in reconciled.records if r.record_id == "same")
    assert (current.entry_name, current.state, current.first_managed_at, current.last_seen_at) == (
        "renamed",
        "active",
        "00",
        "03",
    )
