"""Offline integration of location, loading, logging, operations and CLI exits."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from dnsleaf.cli import app
from dnsleaf.commands import common
from dnsleaf.discovery.models import DiscoveryResult
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.sync.runner import SyncRunner
from dnsleaf.workspace import locator
from dnsleaf.workspace.entries import EntryService
from dnsleaf.workspace.service import WorkspaceService
from dnsleaf.workspace.storage import WorkspaceStorage, dump_yaml_data
from tests.conftest import scaffold_workspace
from tests.fakes import FakeDiscoveryBackend, FakeDNSProvider, FakeSystemdManager

runner = CliRunner()


@pytest.mark.parametrize(
    "command",
    [
        ["validate"],
        ["render"],
        ["apply", "--run-sync"],
        ["uninstall"],
        ["status"],
        ["doctor"],
        ["plan"],
        ["sync-once"],
        ["sync-once", "--apply"],
        ["entry", "list"],
        ["entry", "update", "node", "--fqdn", "service.example.com"],
        ["entry", "remove", "node"],
        ["entry", "enable", "node"],
        ["entry", "disable", "node"],
        [
            "entry",
            "add",
            "local",
            "--name",
            "other",
            "--fqdn",
            "other.example.com",
            "--family",
            "ipv4",
        ],
        ["provider", "verify"],
        ["discover", "local", "--family", "ipv6"],
    ],
)
def test_one_location_load_and_same_logging_snapshot(
    workspace_dir: Path, tmp_path: Path, monkeypatch, command
):
    EntryService().add_entry(
        WorkspaceStorage().load(workspace_dir),
        name="node",
        fqdn="node.example.com",
        source_kind="local",
        family="ipv6",
    )
    provider = FakeDNSProvider()
    sync = SyncRunner(
        provider_factory=lambda _: provider, discovery_backends={"local": FakeDiscoveryBackend()}
    )
    service = WorkspaceService(runner=sync, systemd_manager=FakeSystemdManager(tmp_path / "units"))
    monkeypatch.setattr(common, "workspace_service", lambda _: service)
    monkeypatch.setattr(common, "debug_runner", lambda _: sync)
    monkeypatch.setattr(common, "require_root", lambda operation: None)
    monkeypatch.setattr("dnsleaf.workspace.service.CloudflareDNSProvider", lambda config: provider)
    selections = Mock(wraps=locator.missing_source_files)
    monkeypatch.setattr(locator, "missing_source_files", selections)
    original_load = WorkspaceStorage.load
    loads = []

    def load(storage, path):
        loaded = original_load(storage, path)
        loads.append(loaded)
        return loaded

    monkeypatch.setattr(WorkspaceStorage, "load", load)
    from dnsleaf.logging import runtime

    original_logging = runtime.load_workspace_logging_config
    logging_snapshots = []

    def logging_config(path, *, loaded_workspace=None):
        logging_snapshots.append(loaded_workspace)
        return original_logging(path, loaded_workspace=loaded_workspace)

    monkeypatch.setattr(runtime, "load_workspace_logging_config", logging_config)
    validation_snapshots = []
    validate = WorkspaceStorage.validate_loaded

    def validate_loaded(storage, loaded):
        validation_snapshots.append(loaded)
        return validate(storage, loaded)

    monkeypatch.setattr(WorkspaceStorage, "validate_loaded", validate_loaded)
    result = runner.invoke(app, [*command, "--workspace", str(workspace_dir)])
    assert result.exit_code == 0, result.output
    assert selections.call_count == 1 and len(loads) == 1
    assert all(snapshot is loads[0] for snapshot in logging_snapshots + validation_snapshots)
    if command[0] not in {"status", "doctor"}:
        assert logging_snapshots == loads


def test_partial_warning_json_and_file_logging(workspace_dir: Path, tmp_path: Path, monkeypatch):
    partial = tmp_path / "a-partial"
    partial.mkdir()
    (partial / "workspace.yaml").write_text("malformed: [")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["workspace_root"] == str(workspace_dir)
    assert "possibly incomplete" in result.stderr and "missing entries.yaml" in result.stderr
    assert str(partial) in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        ["validate"],
        ["render"],
        ["apply"],
        ["uninstall"],
        ["status"],
        ["doctor"],
        ["plan"],
        ["sync-once", "--apply"],
        ["provider", "verify"],
        ["entry", "list"],
        ["discover", "local"],
    ],
)
def test_complete_invalid_first_candidate_never_falls_back_or_mutates(
    tmp_path, monkeypatch, command
):
    first = scaffold_workspace(tmp_path, "a-invalid")
    second = scaffold_workspace(tmp_path, "z-valid")
    (first / "workspace.yaml").write_text("zone_name: [\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(common, "require_root", lambda operation: None)
    load = Mock(wraps=WorkspaceStorage().load)
    monkeypatch.setattr(WorkspaceStorage, "load", lambda self, path: load(path))
    provider = Mock(side_effect=AssertionError("provider must not be constructed"))
    monkeypatch.setattr("dnsleaf.workspace.service.CloudflareDNSProvider", provider)
    before = {p: p.read_bytes() for root in [first, second] for p in root.rglob("*") if p.is_file()}
    result = runner.invoke(app, [*command, "--json"])
    assert result.exit_code == 1
    assert str(first) in result.output and "workspace.yaml" in result.output
    assert "line 2, column 1" in result.output
    assert load.call_count == 1 and load.call_args.args[0] == first
    assert not provider.called
    assert before == {
        p: p.read_bytes() for root in [first, second] for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("mode", ["absent", "partial", "explicit", "env", "io-error"])
def test_discovery_outside_mode_only_for_genuine_absence(tmp_path, monkeypatch, mode):
    monkeypatch.chdir(tmp_path)
    backend = FakeDiscoveryBackend()
    sync = SyncRunner(
        provider_factory=lambda _: FakeDNSProvider(), discovery_backends={"local": backend}
    )
    calls = Mock(wraps=sync.discover_target_families)
    monkeypatch.setattr(sync, "discover_target_families", calls)
    monkeypatch.setattr(common, "debug_runner", lambda _: sync)
    args = ["discover", "local", "--family", "ipv6", "--json"]
    if mode == "partial":
        (tmp_path / "entries.yaml").write_text("entries: []")
    elif mode == "explicit":
        args.extend(["-w", str(tmp_path)])
    elif mode == "env":
        monkeypatch.setenv("DNSLEAF_WORKSPACE", str(tmp_path))
    elif mode == "io-error":
        (tmp_path / "workspace.yaml").mkdir()
    result = runner.invoke(app, args)
    assert result.exit_code == (0 if mode == "absent" else 1), result.output
    assert calls.call_count == int(mode == "absent")
    if mode != "absent":
        assert not result.stdout


@pytest.mark.parametrize("error", [None, "Guest agent unavailable"])
def test_failed_discovery_json_does_not_catch_its_own_exit(tmp_path, monkeypatch, error):
    monkeypatch.chdir(tmp_path)
    backend = Mock()
    backend.discover.return_value = DiscoveryResult(
        target=TargetRef(kind=TargetKind.LOCAL), backend="fake", candidates=[], error=error
    )
    sync = SyncRunner(
        provider_factory=lambda _: FakeDNSProvider(), discovery_backends={"local": backend}
    )
    monkeypatch.setattr(common, "debug_runner", lambda _: sync)
    result = runner.invoke(app, ["discover", "local", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == error
    assert payload["selections"]["ipv6"]["status"] == "no_candidate"
    assert not result.stderr


def test_help_version_and_init_ignore_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DNSLEAF_WORKSPACE", str(tmp_path / "does-not-exist"))
    inspect = Mock(side_effect=AssertionError("must not search"))
    monkeypatch.setattr(locator, "missing_source_files", inspect)
    for command in [
        ["--help"],
        ["--version"],
        ["entry", "--help"],
        ["init", str(tmp_path / "new")],
    ]:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
    assert (tmp_path / "new" / "entries.yaml").is_file()
    assert not inspect.called


def test_explicit_dot_overrides_environment_in_command(tmp_path, monkeypatch):
    first = scaffold_workspace(tmp_path, "first")
    second = scaffold_workspace(tmp_path, "second")
    monkeypatch.chdir(first)
    monkeypatch.setenv("DNSLEAF_WORKSPACE", str(second))
    explicit = runner.invoke(app, ["validate", "-w", ".", "--json"])
    implicit = runner.invoke(app, ["validate", "--json"])
    assert json.loads(explicit.stdout)["workspace_root"] == str(first)
    assert json.loads(implicit.stdout)["workspace_root"] == str(second)


def test_stdout_logging_does_not_corrupt_json(workspace_dir, monkeypatch):
    dump_yaml_data(workspace_dir / "workspace.yaml", {"dnsleaf_logging": {"stream": "stdout"}})
    result = runner.invoke(app, ["validate", "-w", str(workspace_dir), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["entry_count"] == 0
    assert "validated" in result.stderr


def test_runtime_validation_failure_names_selected_root_and_field_without_fallback(
    tmp_path, monkeypatch
):
    first = scaffold_workspace(tmp_path, "a-invalid")
    scaffold_workspace(tmp_path, "z-valid")
    external = tmp_path / "missing-external-token"
    dump_yaml_data(first / "workspace.yaml", {"api_token_file": str(external)})
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", "--json"])
    assert result.exit_code == 1
    message = json.loads(result.stderr)["error"]
    assert str(first) in message and str(first / "workspace.yaml") in message
    assert "api_token_file" in message and str(external) in message
    assert not result.stdout


def test_status_retains_config_diagnostic_when_state_is_also_invalid(workspace_dir):
    (workspace_dir / "workspace.yaml").write_text("zone_name: [")
    (workspace_dir / "state" / "managed-records.json").write_text("{")
    (workspace_dir / "state" / "last-apply.json").write_text("{")
    result = runner.invoke(app, ["status", "-w", str(workspace_dir), "--json"])
    assert result.exit_code == 1
    errors = json.loads(result.stdout)["errors"]
    assert len(errors) == 3
    assert "invalid YAML" in errors[0]
    assert "managed-records.json" in errors[1] and "last-apply.json" in errors[2]
