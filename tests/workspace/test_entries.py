from __future__ import annotations

from pathlib import Path

from arbor_ddns.workspace.entries import EntryService


def test_entry_add_update_enable_disable_remove(workspace_dir: Path) -> None:
    service = EntryService()

    added = service.add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        ttl=60,
    )
    assert added.changed is True
    assert added.entry is not None
    assert added.entry.record_type == "AAAA"

    entries = service.list_entries(workspace_dir)
    assert len(entries) == 1
    assert entries[0].name == "web"

    updated = service.update_entry(
        workspace_dir,
        name="web",
        fqdn="new.example.com",
        proxied=True,
        enabled=False,
        description="updated",
    )
    assert updated.entry is not None
    assert updated.entry.fqdn == "new.example.com"
    assert updated.entry.proxied is True
    assert updated.entry.enabled is False

    enabled = service.set_enabled(workspace_dir, name="web", enabled=True)
    assert enabled.entry is not None
    assert enabled.entry.enabled is True

    removed = service.remove_entry(workspace_dir, name="web")
    assert removed.removed_name == "web"
    assert service.list_entries(workspace_dir) == []
