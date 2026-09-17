from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from dnsleaf.config.outside_workspace import OutsideWorkspaceConfig
from dnsleaf.dns.models import DNSRecord
from dnsleaf.sync.runner import SyncRunner
from dnsleaf.workspace.entries import EntryService
from dnsleaf.workspace.models import EntriesFile, WorkspaceConfig
from dnsleaf.workspace.service import WorkspaceService
from dnsleaf.workspace.state import load_managed_records
from dnsleaf.workspace.storage import WorkspaceLoadError, WorkspaceStorage, dump_yaml_data
from tests.fakes import FakeDNSProvider

INVALID_DOCUMENTS = [
    pytest.param("", id="empty-file"),
    pytest.param("  \n \n", id="whitespace-only"),
    pytest.param("# unfinished entries\n", id="comment-only"),
    pytest.param("null\n", id="null"),
    pytest.param("~\n", id="null-shorthand"),
    pytest.param("{}\n", id="empty-mapping"),
    pytest.param("config_version: 2\n", id="missing-entries"),
    pytest.param("entries: null\n", id="null-entries"),
    pytest.param("entries: {}\n", id="mapping-entries"),
    pytest.param("entries: invalid\n", id="scalar-entries"),
    pytest.param("entries: [null]\n", id="null-entry"),
    pytest.param("entries: [42]\n", id="scalar-entry"),
    pytest.param("entries: [{}]\n", id="incomplete-entry"),
    pytest.param("[]\n", id="list-root"),
    pytest.param("false\n", id="boolean-root"),
    pytest.param("42\n", id="number-root"),
    pytest.param("invalid\n", id="string-root"),
]


@pytest.mark.parametrize("document", INVALID_DOCUMENTS)
def test_entries_constructors_reject_invalid_documents(tmp_path: Path, document: str) -> None:
    file = tmp_path / "entries.yaml"
    file.write_text(document, encoding="utf-8")

    with pytest.raises(ValueError):
        EntriesFile.from_file(file)
    with pytest.raises(ValueError):
        EntriesFile.from_mapping(yaml.safe_load(document))


def test_missing_entries_error_explains_explicit_empty_list() -> None:
    with pytest.raises(ValueError, match="explicit 'entries' field.*entries: \\[\\]"):
        EntriesFile.from_mapping({"config_version": 2})


def test_unrelated_configs_still_accept_empty_overrides() -> None:
    assert WorkspaceConfig.from_mapping({}) == WorkspaceConfig.from_defaults()
    assert OutsideWorkspaceConfig.from_mapping({}) == OutsideWorkspaceConfig.from_defaults()


def _managed_service(workspace_dir: Path) -> tuple[WorkspaceService, FakeDNSProvider, Mock]:
    """Seed real managed state using a static entry and a mutation-tracking fake."""

    EntryService().add_entry(
        WorkspaceStorage().load(workspace_dir),
        name="web",
        source_kind="static",
        fqdn="host.example.com",
        family="ipv4",
        static_ipv4="93.184.216.34",
    )
    provider = FakeDNSProvider(
        initial_records=[
            DNSRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                value="2001:4860::88",
                ttl=300,
                record_id="untracked",
                proxied=False,
            )
        ]
    )
    provider_factory = Mock(return_value=provider)
    service = WorkspaceService(runner=SyncRunner(provider_factory=provider_factory))
    report = service.sync_once(WorkspaceStorage().load(workspace_dir), apply=True)
    assert not report.has_errors()
    assert provider.applied_actions == ["create"]
    paths = WorkspaceStorage().paths_for(workspace_dir)
    assert len(load_managed_records(paths).records) == 1
    provider.applied_actions.clear()
    provider_factory.reset_mock()
    return service, provider, provider_factory


@pytest.mark.parametrize("document", INVALID_DOCUMENTS)
@pytest.mark.parametrize("prune_managed", [False, True], ids=["no-prune", "prune"])
def test_invalid_entries_fail_public_loading_paths_before_planning(
    workspace_dir: Path, document: str, prune_managed: bool
) -> None:
    service, provider, provider_factory = _managed_service(workspace_dir)
    storage = WorkspaceStorage()
    paths = storage.paths_for(workspace_dir)
    config = yaml.safe_load(paths.workspace_file.read_text(encoding="utf-8"))
    config["apply"]["prune_managed_records"] = prune_managed
    dump_yaml_data(paths.workspace_file, config)
    paths.entries_file.write_text(document, encoding="utf-8")
    original_state = {file.name: file.read_bytes() for file in paths.state_dir.iterdir()}
    original_records = provider.list_records("host.example.com")

    for operation in (
        storage.load,
        storage.validate,
        lambda path: service.validate_workspace(storage.load(path)),
        lambda path: service.plan_workspace(storage.load(path)),
        lambda path: service.sync_once(storage.load(path), apply=False),
        lambda path: service.sync_once(storage.load(path), apply=True),
    ):
        with pytest.raises((ValueError, WorkspaceLoadError)):
            operation(workspace_dir)

        # SyncRunner creates the provider before any DNS planning; never reach it.
        provider_factory.assert_not_called()
        assert provider.applied_actions == []
        assert provider.list_records("host.example.com") == original_records
        assert {
            file.name: file.read_bytes() for file in paths.state_dir.iterdir()
        } == original_state


@pytest.mark.parametrize("prune_managed", [False, True], ids=["no-prune", "prune"])
def test_explicit_empty_entries_preserve_intentional_pruning(
    workspace_dir: Path, prune_managed: bool
) -> None:
    service, provider, _ = _managed_service(workspace_dir)
    paths = WorkspaceStorage().paths_for(workspace_dir)
    paths.entries_file.write_text("config_version: 2\nentries: []\n", encoding="utf-8")
    original_state = paths.managed_records_file.read_bytes()
    original_records = provider.list_records("host.example.com")
    untracked = provider.list_records("host.example.com", "AAAA")

    assert EntriesFile.from_file(paths.entries_file).entries == []
    assert WorkspaceStorage().load(workspace_dir).entries_file.entries == []
    assert service.validate_workspace(WorkspaceStorage().load(workspace_dir)).entry_count == 0

    plan = service.plan_workspace(
        WorkspaceStorage().load(workspace_dir), prune_managed=prune_managed
    )
    assert not plan.has_errors()
    assert plan.dry_run is True
    assert len(plan.prune_outcomes) == int(prune_managed)
    assert provider.applied_actions == []
    assert provider.list_records("host.example.com") == original_records
    assert paths.managed_records_file.read_bytes() == original_state

    report = service.sync_once(
        WorkspaceStorage().load(workspace_dir), apply=True, prune_managed=prune_managed
    )
    assert not report.has_errors()
    assert report.record_outcomes == []
    assert provider.list_records("host.example.com", "AAAA") == untracked
    state = load_managed_records(paths)
    if prune_managed:
        assert len(report.prune_outcomes) == 1
        assert report.prune_outcomes[0].applied is True
        assert provider.applied_actions == ["delete"]
        assert provider.list_records("host.example.com") == untracked
        assert state.records == []
    else:
        assert report.prune_outcomes == []
        assert provider.applied_actions == []
        assert provider.list_records("host.example.com") == original_records
        assert len(state.records) == 1
        assert state.records[0].state == "stale"
