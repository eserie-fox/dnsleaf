from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from dnsleaf.workspace.entries import EntryService
from dnsleaf.workspace.models import EntriesFile
from dnsleaf.workspace.storage import WorkspaceStorage, dump_yaml_data


def entry(name="first", fqdn="host.example.com", family="ipv6", enabled=True):
    return dict(
        name=name,
        fqdn=fqdn,
        family=family,
        enabled=enabled,
        source_kind="local",
        selection_policy="default",
    )


@pytest.mark.parametrize(
    "family1,family2", [("ipv6", "ipv6"), ("both", "ipv4"), ("both", "ipv6"), ("both", "both")]
)
def test_enabled_target_collisions_rejected(family1: str, family2: str):
    with pytest.raises(
        ValidationError, match="enabled entries 'first' and 'second'.*host.example.com"
    ):
        EntriesFile.from_mapping(
            {"entries": [entry(family=family1), entry("second", "HOST.Example.Com.", family2)]}
        )


@pytest.mark.parametrize(
    "second",
    [
        entry("second", family="ipv4"),
        entry("second", fqdn="service.example.com"),
        entry("second", enabled=False),
    ],
)
def test_independent_targets_and_disabled_duplicates_allowed(second):
    assert len(EntriesFile.from_mapping({"entries": [entry(), second]}).entries) == 2


def test_unique_names_still_independent():
    with pytest.raises(ValidationError, match="duplicate entry names"):
        EntriesFile.from_mapping({"entries": [entry(), entry(fqdn="other.example.com")]})


@pytest.mark.parametrize("action", ["add", "update", "enable"])
def test_failed_entry_edit_keeps_file_unchanged(workspace_dir: Path, action: str):
    second = entry("second", fqdn="other.example.com")
    if action == "enable":
        second = entry("second", enabled=False)
    path = workspace_dir / "entries.yaml"
    dump_yaml_data(path, {"entries": [entry(), second]})
    before = path.read_bytes()
    loaded = WorkspaceStorage().load(workspace_dir)
    service = EntryService()
    with pytest.raises(ValidationError, match="both manage host.example.com AAAA"):
        if action == "add":
            service.add_entry(
                loaded, name="third", source_kind="local", family="ipv6", fqdn="HOST.example.com."
            )
        elif action == "update":
            service.update_entry(loaded, name="second", fqdn="HOST.example.com.")
        else:
            service.set_enabled(loaded, name="second", enabled=True)
    assert path.read_bytes() == before
    assert loaded.entries_file.entries[1].fqdn == second["fqdn"]
