from __future__ import annotations

from pathlib import Path

from arbor_ddns.workspace.entries import EntryService


def test_entry_add_update_enable_disable_remove_dynamic_entry(workspace_dir: Path) -> None:
    service = EntryService()

    added = service.add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
        ttl=60,
    )
    assert added.changed is True
    assert added.entry is not None
    assert added.entry.family.value == "ipv6"

    entries = service.list_entries(workspace_dir)
    assert len(entries) == 1
    assert entries[0].name == "web"

    updated = service.update_entry(
        workspace_dir,
        name="web",
        fqdn="new.example.com",
        family="both",
        proxied=True,
        enabled=False,
        description="updated",
    )
    assert updated.entry is not None
    assert updated.entry.fqdn == "new.example.com"
    assert updated.entry.family.value == "both"
    assert updated.entry.proxied is True
    assert updated.entry.enabled is False

    enabled = service.set_enabled(workspace_dir, name="web", enabled=True)
    assert enabled.entry is not None
    assert enabled.entry.enabled is True

    removed = service.remove_entry(workspace_dir, name="web")
    assert removed.removed_name == "web"
    assert service.list_entries(workspace_dir) == []


def test_entry_add_and_update_static_entry(workspace_dir: Path) -> None:
    service = EntryService()

    added = service.add_entry(
        workspace_dir,
        name="edge",
        source_kind="static",
        fqdn="edge.example.com",
        family="both",
        static_ipv4="93.184.216.34",
        static_ipv6="2408:8266:5003:506a::88",
    )

    assert added.entry is not None
    assert added.entry.source_kind.value == "static"
    assert added.entry.static_ipv4 == "93.184.216.34"
    assert added.entry.static_ipv6 == "2408:8266:5003:506a::88"

    updated = service.update_entry(
        workspace_dir,
        name="edge",
        family="ipv4",
        static_ipv4="8.8.8.8",
    )

    assert updated.entry is not None
    assert updated.entry.family.value == "ipv4"
    assert updated.entry.static_ipv4 == "8.8.8.8"
