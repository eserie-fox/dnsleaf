"""Workspace state helpers."""

from __future__ import annotations

import json

from dnsleaf.dns.identity import dns_target
from dnsleaf.workspace.models import (
    EntriesFile,
    LastApplyState,
    ManagedRecordFile,
    ManagedRecordSnapshot,
)
from dnsleaf.workspace.reports import WorkspaceRunReport
from dnsleaf.workspace.storage import LoadedWorkspace, WorkspacePaths, dump_json_data


def load_managed_records(paths: WorkspacePaths) -> ManagedRecordFile:
    """Load managed record state, or return an empty state file."""

    if not paths.managed_records_file.exists():
        return ManagedRecordFile()
    payload = json.loads(paths.managed_records_file.read_text(encoding="utf-8"))
    return ManagedRecordFile.model_validate(payload)


def write_managed_records(paths: WorkspacePaths, state: ManagedRecordFile) -> None:
    """Persist managed record state."""

    dump_json_data(paths.managed_records_file, state.model_dump(mode="json"))


def load_last_apply(paths: WorkspacePaths) -> LastApplyState | None:
    """Load last apply state if available."""

    if not paths.last_apply_file.exists():
        return None
    payload = json.loads(paths.last_apply_file.read_text(encoding="utf-8"))
    return LastApplyState.model_validate(payload)


def write_last_apply(paths: WorkspacePaths, state: LastApplyState) -> None:
    """Persist last apply state."""

    dump_json_data(paths.last_apply_file, state.model_dump(mode="json"))


def managed_record_counts(state: ManagedRecordFile) -> tuple[int, int]:
    """Return `(active_count, stale_count)`."""

    active = sum(1 for record in state.records if record.state == "active")
    stale = sum(1 for record in state.records if record.state == "stale")
    return active, stale


def enabled_dns_targets(entries: EntriesFile) -> dict[tuple[str, str], str]:
    """Map configured targets to entry labels, independently of discovery results."""

    return {
        dns_target(entry.fqdn, family.record_type): entry.name
        for entry in entries.enabled_entries()
        for family in entry.concrete_families()
    }


def stale_records_for_desired(
    state: ManagedRecordFile,
    *,
    desired_targets: set[tuple[str, str]],
) -> list[ManagedRecordSnapshot]:
    """Return managed records that are no longer desired by enabled entries."""

    return [
        record
        for record in state.records
        if dns_target(record.fqdn, record.record_type) not in desired_targets
    ]


def reconcile_managed_state(
    loaded: LoadedWorkspace,
    state: ManagedRecordFile,
    report: WorkspaceRunReport,
    *,
    now: str,
) -> ManagedRecordFile:
    """Reconcile ownership from desired targets and outcomes without mutating prior state."""

    desired_targets = enabled_dns_targets(loaded.entries_file)
    records_by_identity: dict[tuple[str, str, str | None], ManagedRecordSnapshot] = {}

    # Keep the newest observation for duplicate snapshots of one remote record,
    # while preserving its first ownership timestamp and current configured label.
    for record in sorted(state.records, key=lambda item: item.last_seen_at):
        target = dns_target(record.fqdn, record.record_type)
        identity = (*target, record.record_id)
        existing = records_by_identity.get(identity)
        records_by_identity[identity] = record.model_copy(
            update={
                "fqdn": target[0],
                "record_type": target[1],
                "entry_name": desired_targets.get(target, record.entry_name),
                "state": "active" if target in desired_targets else "stale",
                "first_managed_at": min(existing.first_managed_at, record.first_managed_at)
                if existing is not None
                else record.first_managed_at,
                "last_seen_at": now,
            }
        )

    for outcome in report.record_outcomes:
        if outcome.final_record is None:
            continue
        target = dns_target(outcome.fqdn, outcome.record_type)
        record_id = outcome.final_record.record_id
        matching = [
            identity
            for identity in records_by_identity
            if identity[:2] == target or (record_id is not None and identity[2] == record_id)
        ]
        first_managed_at = min(
            (
                records_by_identity[identity].first_managed_at
                for identity in matching
                if identity[2] == record_id
            ),
            default=now,
        )
        # Successful normal sync establishes the current single record for this
        # target. Replace obsolete snapshots, including aliases of the same ID.
        for identity in matching:
            del records_by_identity[identity]
        records_by_identity[(*target, record_id)] = ManagedRecordSnapshot(
            workspace_name=loaded.resolved_workspace.workspace_name,
            entry_name=desired_targets[target],
            fqdn=target[0],
            record_type=target[1],
            record_id=record_id,
            value=outcome.final_record.value,
            ttl=outcome.final_record.ttl,
            proxied=outcome.final_record.proxied,
            state="active",
            first_managed_at=first_managed_at,
            last_seen_at=now,
        )

    for prune_outcome in report.prune_outcomes:
        if prune_outcome.status not in {"applied", "confirmed_absent"}:
            continue
        identity = (
            *dns_target(prune_outcome.fqdn, prune_outcome.record_type),
            prune_outcome.record_id,
        )
        records_by_identity.pop(identity, None)

    return ManagedRecordFile(
        records=sorted(
            records_by_identity.values(),
            key=lambda record: (record.fqdn, record.record_type, record.record_id or ""),
        )
    )
