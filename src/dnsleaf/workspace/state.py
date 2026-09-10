"""Workspace state helpers."""

from __future__ import annotations

import json

from dnsleaf.workspace.models import LastApplyState, ManagedRecordFile, ManagedRecordSnapshot
from dnsleaf.workspace.storage import WorkspacePaths, dump_json_data


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


def stale_records_for_desired(
    state: ManagedRecordFile,
    *,
    enabled_descriptors: set[str],
) -> list[ManagedRecordSnapshot]:
    """Return managed records that are no longer desired by enabled entries."""

    return [
        record
        for record in state.records
        if record.state == "stale" or record.descriptor not in enabled_descriptors
    ]
