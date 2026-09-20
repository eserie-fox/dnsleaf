"""Entry CRUD facade for `entries.yaml`."""

from __future__ import annotations

from dnsleaf.dns.models import TTLSetting
from dnsleaf.models import EntryAddressFamily, EntrySourceKind
from dnsleaf.workspace.models import EntriesFile, WorkspaceEntry
from dnsleaf.workspace.reports import EntryMutationResult
from dnsleaf.workspace.storage import LoadedWorkspace, WorkspaceLoadError, dump_yaml_data
from dnsleaf.workspace.strategy import resolve_entry_strategies


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
        evidence: str | None = None,
        ttl: TTLSetting | None = None,
        proxied: bool | None = None,
        description: str | None = None,
        static_ipv4: str | None = None,
        static_ipv6: str | None = None,
    ) -> EntryMutationResult:
        """Add one workspace entry."""

        if loaded.entries_file.get(name) is not None:
            raise WorkspaceLoadError(f"entry already exists: {name}")
        entry = WorkspaceEntry.model_validate(
            dict(
                name=name,
                source_kind=EntrySourceKind(source_kind),
                source_id=source_id,
                fqdn=fqdn,
                family=EntryAddressFamily(family),
                selection_policy=selection_policy,
                evidence=evidence,
                enabled=True,
                ttl=ttl,
                proxied=proxied,
                description=description,
                static_ipv4=static_ipv4,
                static_ipv6=static_ipv6,
            )
        )
        updated = EntriesFile(
            config_version=loaded.entries_file.config_version,
            entries=[*loaded.entries_file.entries, entry],
        )
        self._write_entries(loaded, updated)
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
        evidence: str | None = None,
        enabled: bool | None = None,
        ttl: TTLSetting | None = None,
        proxied: bool | None = None,
        inherit_proxied: bool = False,
        inherit_selection_policy: bool = False,
        inherit_evidence: bool = False,
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
        if inherit_selection_policy and selection_policy is not None:
            raise ValueError("cannot set selection_policy and inherit_selection_policy together")
        if inherit_evidence and evidence is not None:
            raise ValueError("cannot set evidence and inherit_evidence together")
        if inherit_selection_policy:
            patch["selection_policy"] = None
        elif selection_policy is not None:
            patch["selection_policy"] = selection_policy
        if inherit_evidence:
            patch["evidence"] = None
        elif evidence is not None:
            patch["evidence"] = evidence
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
            loaded,
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
            loaded,
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

    def _write_entries(self, loaded: LoadedWorkspace, entries: EntriesFile) -> None:
        resolve_entry_strategies(loaded.workspace_config, entries)
        dump_yaml_data(
            loaded.paths.entries_file, entries.model_dump(mode="json", exclude_none=True)
        )
