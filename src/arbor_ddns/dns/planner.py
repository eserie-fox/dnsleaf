"""Planner for desired AAAA state versus current provider state."""

from __future__ import annotations

from arbor_ddns.dns.models import DesiredRecord, DNSRecord, PlannedChange, SyncPlan


def plan_dns_changes(
    *,
    current_records: list[DNSRecord],
    desired_record: DesiredRecord | None,
) -> SyncPlan:
    """Generate a deterministic create/update/delete/noop plan."""

    if desired_record is None:
        if not current_records:
            return SyncPlan(
                provider="unknown",
                fqdn="unknown",
                record_type="AAAA",
                desired=None,
                changes=[
                    PlannedChange(
                        action="noop",
                        provider="unknown",
                        fqdn="unknown",
                        record_type="AAAA",
                        reason="no desired record and no current record",
                    )
                ],
            )
        return SyncPlan(
            provider=current_records[0].provider,
            fqdn=current_records[0].fqdn,
            record_type=current_records[0].record_type,
            desired=None,
            changes=[
                PlannedChange(
                    action="delete",
                    provider=record.provider,
                    fqdn=record.fqdn,
                    record_type=record.record_type,
                    current=record,
                    reason="no desired record remains",
                )
                for record in current_records
            ],
        )

    if not current_records:
        return SyncPlan(
            provider=desired_record.provider,
            fqdn=desired_record.fqdn,
            record_type=desired_record.record_type,
            desired=desired_record,
            changes=[
                PlannedChange(
                    action="create",
                    provider=desired_record.provider,
                    fqdn=desired_record.fqdn,
                    record_type=desired_record.record_type,
                    desired=desired_record,
                    reason="record does not exist yet",
                )
            ],
        )

    exact_matches = [
        record
        for record in current_records
        if record.value == desired_record.value and record.ttl == desired_record.ttl
    ]
    if exact_matches and len(current_records) == 1:
        return SyncPlan(
            provider=desired_record.provider,
            fqdn=desired_record.fqdn,
            record_type=desired_record.record_type,
            desired=desired_record,
            changes=[
                PlannedChange(
                    action="noop",
                    provider=desired_record.provider,
                    fqdn=desired_record.fqdn,
                    record_type=desired_record.record_type,
                    current=current_records[0],
                    desired=desired_record,
                    reason="current record already matches desired state",
                )
            ],
        )

    if exact_matches:
        matching = exact_matches[0]
        return SyncPlan(
            provider=desired_record.provider,
            fqdn=desired_record.fqdn,
            record_type=desired_record.record_type,
            desired=desired_record,
            changes=[
                PlannedChange(
                    action="delete",
                    provider=record.provider,
                    fqdn=record.fqdn,
                    record_type=record.record_type,
                    current=record,
                    desired=desired_record,
                    reason=(
                        "extra record should be removed because one exact desired "
                        "record already exists"
                    ),
                )
                for record in current_records
                if record != matching
            ],
        )

    primary_record = current_records[0]
    changes = [
        PlannedChange(
            action="update",
            provider=primary_record.provider,
            fqdn=primary_record.fqdn,
            record_type=primary_record.record_type,
            current=primary_record,
            desired=desired_record,
            reason="current record differs from desired state",
        )
    ]
    changes.extend(
        PlannedChange(
            action="delete",
            provider=record.provider,
            fqdn=record.fqdn,
            record_type=record.record_type,
            current=record,
            desired=desired_record,
            reason="extra record should be removed after primary record update",
        )
        for record in current_records[1:]
    )
    return SyncPlan(
        provider=desired_record.provider,
        fqdn=desired_record.fqdn,
        record_type=desired_record.record_type,
        desired=desired_record,
        changes=changes,
    )
