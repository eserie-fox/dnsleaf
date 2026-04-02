from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from arbor_ddns.dns.models import AUTO_TTL
from arbor_ddns.models import EntrySourceKind, TargetKind
from arbor_ddns.workspace.entries import EntryService
from arbor_ddns.workspace.models import WorkspaceConfig, WorkspaceEntry


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


def test_entry_add_local_entry(workspace_dir: Path) -> None:
    service = EntryService()

    added = service.add_entry(
        workspace_dir,
        name="self",
        source_kind="local",
        fqdn="self.example.com",
        family="ipv6",
    )

    assert added.entry is not None
    assert added.entry.source_kind is EntrySourceKind.LOCAL
    assert added.entry.selection_policy == "default"
    assert added.entry.source_id is None


def test_entry_service_accepts_auto_ttl(workspace_dir: Path) -> None:
    service = EntryService()

    added = service.add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
        ttl="auto",
    )

    assert added.entry is not None
    assert added.entry.ttl == "auto"


def test_workspace_config_accepts_auto_ttl_and_null_default_proxied(tmp_path: Path) -> None:
    config = WorkspaceConfig.scaffold_defaults("lab")

    resolved = config.resolve(tmp_path / "lab")

    assert config.default_ttl == "auto"
    assert config.default_proxied is None
    assert resolved.default_ttl == AUTO_TTL
    assert resolved.default_proxied is None


def test_workspace_entry_effective_ttl_and_proxied_support_auto_and_null() -> None:
    entry = WorkspaceEntry(
        name="self",
        source_kind="local",
        fqdn="self.example.com",
        family="ipv6",
        selection_policy="default",
        enabled=True,
        ttl="auto",
    )

    assert entry.effective_ttl(default_ttl=300) == AUTO_TTL
    assert entry.effective_proxied(default_proxied=None) is None


def test_entry_update_leaves_existing_proxied_override_when_omitted(workspace_dir: Path) -> None:
    service = EntryService()
    service.add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
        proxied=True,
    )

    updated = service.update_entry(
        workspace_dir,
        name="web",
        fqdn="new.example.com",
    )

    assert updated.entry is not None
    assert updated.entry.proxied is True


def test_entry_update_sets_proxied_false(workspace_dir: Path) -> None:
    service = EntryService()
    service.add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
        proxied=True,
    )

    updated = service.update_entry(
        workspace_dir,
        name="web",
        proxied=False,
    )

    assert updated.entry is not None
    assert updated.entry.proxied is False


def test_entry_update_can_clear_proxied_override_to_inherit(workspace_dir: Path) -> None:
    service = EntryService()
    service.add_entry(
        workspace_dir,
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="host.example.com",
        family="ipv6",
        proxied=True,
    )

    updated = service.update_entry(
        workspace_dir,
        name="web",
        inherit_proxied=True,
    )
    reloaded = service.list_entries(workspace_dir)
    entries_payload = yaml.safe_load((workspace_dir / "entries.yaml").read_text(encoding="utf-8"))

    assert updated.entry is not None
    assert updated.entry.proxied is None
    assert reloaded[0].proxied is None
    assert "proxied" not in entries_payload["entries"][0]


def test_workspace_entry_local_requires_selection_policy() -> None:
    with pytest.raises(ValidationError, match="dynamic local entries require selection_policy"):
        WorkspaceEntry(
            name="self",
            source_kind="local",
            fqdn="self.example.com",
            family="ipv6",
            enabled=True,
        )


def test_workspace_entry_local_forbids_source_id() -> None:
    with pytest.raises(ValidationError, match="dynamic local entries must not define source_id"):
        WorkspaceEntry(
            name="self",
            source_kind="local",
            source_id=101,
            fqdn="self.example.com",
            family="ipv6",
            selection_policy="default",
            enabled=True,
        )


def test_workspace_entry_local_forbids_static_values() -> None:
    with pytest.raises(
        ValidationError,
        match="dynamic local entries must not define static IP values",
    ):
        WorkspaceEntry(
            name="self",
            source_kind="local",
            fqdn="self.example.com",
            family="ipv4",
            selection_policy="default",
            enabled=True,
            static_ipv4="93.184.216.34",
        )


def test_workspace_entry_local_converts_to_local_target_ref() -> None:
    entry = WorkspaceEntry(
        name="self",
        source_kind="local",
        fqdn="self.example.com",
        family="ipv6",
        selection_policy="default",
        enabled=True,
    )

    target = entry.to_target_ref()

    assert target.kind is TargetKind.LOCAL
    assert target.id is None


def test_workspace_entry_source_descriptor_formats_static_local_and_guest_targets() -> None:
    static_entry = WorkspaceEntry(
        name="edge",
        source_kind="static",
        fqdn="edge.example.com",
        family="ipv4",
        enabled=True,
        static_ipv4="93.184.216.34",
    )
    local_entry = WorkspaceEntry(
        name="self",
        source_kind="local",
        fqdn="self.example.com",
        family="ipv6",
        enabled=True,
        selection_policy="default",
    )
    lxc_entry = WorkspaceEntry(
        name="web",
        source_kind="lxc",
        source_id=101,
        fqdn="web.example.com",
        family="ipv6",
        enabled=True,
        selection_policy="default",
    )
    vm_entry = WorkspaceEntry(
        name="guest",
        source_kind="vm",
        source_id=201,
        fqdn="guest.example.com",
        family="ipv6",
        enabled=True,
        selection_policy="default",
    )

    assert static_entry.source_descriptor == "static"
    assert local_entry.source_descriptor == "local"
    assert lxc_entry.source_descriptor == "lxc/101"
    assert vm_entry.source_descriptor == "vm/201"
