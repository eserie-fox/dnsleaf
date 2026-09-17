"""Entry CRUD facade for `entries.yaml`."""

from __future__ import annotations

from pathlib import Path

from dnsleaf.dns.models import TTLSetting
from dnsleaf.models import EntryAddressFamily, EntrySourceKind
from dnsleaf.workspace.models import EntriesFile, WorkspaceEntry
from dnsleaf.workspace.reports import EntryMutationResult
from dnsleaf.workspace.storage import LoadedWorkspace, WorkspaceLoadError, dump_yaml_data


class EntryService:
    """Manage workspace entries through stable file writes."""

    def list_entries(self, loaded: LoadedWorkspace) -> list[WorkspaceEntry]:
        """Return all entries in a workspace."""

        return list(loaded.entries_file.entries)

    def add_entry(
        self,
        loaded: LoadedWorkspace,
        *,
        name: str,
        source_kind: str,
        fqdn: str,
        family: str,
        source_id: int | None = None,
        selection_policy: str | None = None,
        ttl: TTLSetting | None = None,
        proxied: bool | None = None,
        description: str | None = None,
        static_ipv4: str | None = None,
        static_ipv6: str | None = None,
    ) -> EntryMutationResult:
        """Add one workspace entry."""

        if loaded.entries_file.get(name) is not None:
            raise WorkspaceLoadError(f"entry already exists: {name}")
        entry = WorkspaceEntry(
            name=name,
            source_kind=EntrySourceKind(source_kind),
            source_id=source_id,
            fqdn=fqdn,
            family=EntryAddressFamily(family),
            selection_policy=(
                selection_policy
                if EntrySourceKind(source_kind) is EntrySourceKind.STATIC
                else (selection_policy or "default")
            ),
            enabled=True,
            ttl=ttl,
            proxied=proxied,
            description=description,
            static_ipv4=static_ipv4,
            static_ipv6=static_ipv6,
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
        loaded: LoadedWorkspace,
        *,
        name: str,
        fqdn: str | None = None,
        family: str | None = None,
        selection_policy: str | None = None,
        enabled: bool | None = None,
        ttl: TTLSetting | None = None,
        proxied: bool | None = None,
        inherit_proxied: bool = False,
        source_id: int | None = None,
        description: str | None = None,
        static_ipv4: str | None = None,
        static_ipv6: str | None = None,
    ) -> EntryMutationResult:
        """Update a named entry."""

        existing = loaded.entries_file.get(name)
        if existing is None:
            raise WorkspaceLoadError(f"entry not found: {name}")
        patch = existing.model_dump(mode="python")
        if fqdn is not None:
            patch["fqdn"] = fqdn
        if family is not None:
            patch["family"] = family
        if selection_policy is not None:
            patch["selection_policy"] = selection_policy
        if enabled is not None:
            patch["enabled"] = enabled
        if ttl is not None:
            patch["ttl"] = ttl
        if inherit_proxied:
            patch["proxied"] = None
        elif proxied is not None:
            patch["proxied"] = proxied
        if source_id is not None:
            patch["source_id"] = source_id
        if description is not None:
            patch["description"] = description
        if static_ipv4 is not None:
            patch["static_ipv4"] = static_ipv4
        if static_ipv6 is not None:
            patch["static_ipv6"] = static_ipv6
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

    def remove_entry(self, loaded: LoadedWorkspace, *, name: str) -> EntryMutationResult:
        """Remove a named entry."""

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
        loaded: LoadedWorkspace,
        *,
        name: str,
        enabled: bool,
    ) -> EntryMutationResult:
        """Enable or disable a named entry."""

        return self.update_entry(loaded, name=name, enabled=enabled)

    def _write_entries(self, path: Path, entries: EntriesFile) -> None:
        dump_yaml_data(path, entries.model_dump(mode="json", exclude_none=True))
