"""Entry CRUD facade for `entries.yaml`."""

from __future__ import annotations

from pathlib import Path

from arbor_ddns.models import TargetKind
from arbor_ddns.workspace.models import EntriesFile, EntryMutationResult, WorkspaceEntry
from arbor_ddns.workspace.storage import WorkspaceLoadError, WorkspaceStorage, dump_yaml_data


class EntryService:
    """Manage workspace entries through stable file writes."""

    def __init__(self, storage: WorkspaceStorage | None = None) -> None:
        self._storage = storage or WorkspaceStorage()

    def list_entries(self, workspace_dir: str | Path) -> list[WorkspaceEntry]:
        """Return all entries in a workspace."""

        return list(self._storage.load(workspace_dir).entries_file.entries)

    def add_entry(
        self,
        workspace_dir: str | Path,
        *,
        name: str,
        source_kind: str,
        source_id: int,
        fqdn: str,
        selection_policy: str = "default",
        ttl: int | None = None,
        proxied: bool | None = None,
        description: str | None = None,
    ) -> EntryMutationResult:
        """Add an `AAAA` entry."""

        loaded = self._storage.load(workspace_dir)
        if loaded.entries_file.get(name) is not None:
            raise WorkspaceLoadError(f"entry already exists: {name}")
        entry = WorkspaceEntry(
            name=name,
            source_kind=TargetKind(source_kind),
            source_id=source_id,
            fqdn=fqdn,
            record_type="AAAA",
            selection_policy=selection_policy,
            enabled=True,
            ttl=ttl,
            proxied=proxied,
            description=description,
        )
        updated = EntriesFile(
            config_version=loaded.entries_file.config_version,
            entries=[*loaded.entries_file.entries, entry],
        )
        self._write_entries(loaded.paths.entries_file, updated)
        return EntryMutationResult(
            operation="add",
            changed=True,
            message=f"added entry {entry.name}",
            entry=entry,
        )

    def update_entry(
        self,
        workspace_dir: str | Path,
        *,
        name: str,
        fqdn: str | None = None,
        selection_policy: str | None = None,
        enabled: bool | None = None,
        ttl: int | None = None,
        proxied: bool | None = None,
        source_id: int | None = None,
        description: str | None = None,
    ) -> EntryMutationResult:
        """Update a named entry."""

        loaded = self._storage.load(workspace_dir)
        existing = loaded.entries_file.get(name)
        if existing is None:
            raise WorkspaceLoadError(f"entry not found: {name}")
        patch = existing.model_dump(mode="python")
        if fqdn is not None:
            patch["fqdn"] = fqdn
        if selection_policy is not None:
            patch["selection_policy"] = selection_policy
        if enabled is not None:
            patch["enabled"] = enabled
        if ttl is not None:
            patch["ttl"] = ttl
        if proxied is not None:
            patch["proxied"] = proxied
        if source_id is not None:
            patch["source_id"] = source_id
        if description is not None:
            patch["description"] = description
        updated_entry = WorkspaceEntry.model_validate(patch)
        new_entries = [
            updated_entry if entry.name == name else entry for entry in loaded.entries_file.entries
        ]
        self._write_entries(
            loaded.paths.entries_file,
            EntriesFile(config_version=loaded.entries_file.config_version, entries=new_entries),
        )
        return EntryMutationResult(
            operation="update",
            changed=updated_entry != existing,
            message=f"updated entry {name}",
            entry=updated_entry,
        )

    def remove_entry(self, workspace_dir: str | Path, *, name: str) -> EntryMutationResult:
        """Remove a named entry."""

        loaded = self._storage.load(workspace_dir)
        existing = loaded.entries_file.get(name)
        if existing is None:
            raise WorkspaceLoadError(f"entry not found: {name}")
        new_entries = [entry for entry in loaded.entries_file.entries if entry.name != name]
        self._write_entries(
            loaded.paths.entries_file,
            EntriesFile(config_version=loaded.entries_file.config_version, entries=new_entries),
        )
        return EntryMutationResult(
            operation="remove",
            changed=True,
            message=f"removed entry {name}",
            removed_name=name,
        )

    def set_enabled(
        self,
        workspace_dir: str | Path,
        *,
        name: str,
        enabled: bool,
    ) -> EntryMutationResult:
        """Enable or disable a named entry."""

        return self.update_entry(workspace_dir, name=name, enabled=enabled)

    def _write_entries(self, path: Path, entries: EntriesFile) -> None:
        dump_yaml_data(path, entries.model_dump(mode="json", exclude_none=True))
