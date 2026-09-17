"""Workspace search tests use bounded temporary bases, never the real root/home."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from dnsleaf.config.resources import check_regular_readable_file
from dnsleaf.workspace import locator
from dnsleaf.workspace.locator import WorkspaceNotFoundError, locate_workspace, search_bases
from dnsleaf.workspace.storage import WorkspaceLoadError, WorkspaceStorage


def candidate(path: Path, files: tuple[str, ...] = locator.REQUIRED_FILES) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in files:
        (path / name).write_text("entries: []\n" if name == "entries.yaml" else "{}\n")
    return path


def test_cli_environment_and_explicit_dot_precedence(tmp_path: Path) -> None:
    root = candidate(tmp_path)
    child = candidate(root / "child")
    env = {"DNSLEAF_WORKSPACE": str(child)}
    assert locate_workspace(".", cwd=root, env=env) == root
    assert locate_workspace(cwd=root, env=env) == child
    assert locate_workspace(cwd=root, env={}) == child
    assert locate_workspace(cwd=root, env={"DNSLEAF_WORKSPACE": ""}) == child


@pytest.mark.parametrize("via_env", [False, True])
def test_authoritative_missing_path_never_falls_back(tmp_path: Path, via_env: bool) -> None:
    candidate(tmp_path / "valid")
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        locate_workspace(
            None if via_env else missing,
            cwd=tmp_path,
            env={"DNSLEAF_WORKSPACE": str(missing)} if via_env else {},
        )
    candidate(missing, ("workspace.yaml",))
    with pytest.raises(RuntimeError, match="selected workspace.*missing entries.yaml"):
        locate_workspace(
            None if via_env else missing,
            cwd=tmp_path,
            env={"DNSLEAF_WORKSPACE": str(missing)} if via_env else {},
        )


def test_normalization_and_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    child = candidate(tmp_path / "child")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert locate_workspace("~/child/../child", env={}) == child


def test_children_first_sorted_first_match_no_later_inspection(tmp_path: Path) -> None:
    candidate(tmp_path)
    first = candidate(tmp_path / "a")
    candidate(tmp_path / "z")
    (tmp_path / "z" / "workspace.yaml").unlink()
    (tmp_path / "z" / "workspace.yaml").mkdir()
    assert locate_workspace(cwd=tmp_path, env={}) == first


def test_partial_warning_survives_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    partial = candidate(tmp_path / "a", ("workspace.yaml",))
    complete = candidate(tmp_path / "b")
    assert locate_workspace(cwd=tmp_path, env={}) == complete
    output = capsys.readouterr()
    assert not output.out
    assert str(partial) in output.err and "missing entries.yaml" in output.err
    assert "possibly incomplete" in output.err and "another project" in output.err


@pytest.mark.parametrize("files", [(), ("workspace.yaml",), ("entries.yaml",)])
def test_no_complete_summary(tmp_path: Path, files: tuple[str, ...]) -> None:
    child = candidate(tmp_path / "child", files)
    with pytest.raises(WorkspaceNotFoundError) as caught:
        locate_workspace(cwd=tmp_path, env={})
    message = str(caught.value)
    assert str(child) in message and str(tmp_path) in message
    assert "workspace.yaml, entries.yaml" in message
    assert "sorted immediate child directories before the base" in message
    assert "--workspace" in message and "DNSLEAF_WORKSPACE" in message and "init" in message
    assert bool(caught.value.incomplete) == bool(files)


def test_base_order_generation_and_deduplication(tmp_path: Path) -> None:
    cwd = tmp_path / "deep" / "cwd"
    home = tmp_path / "home"
    assert search_bases(cwd, home) == [cwd, *cwd.parents, home]
    assert search_bases(cwd, tmp_path) == [cwd, *cwd.parents]


def test_ancestor_then_home_inspection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = candidate(tmp_path / "ancestor" / "cwd", ())
    ancestor = cwd.parent
    home = candidate(tmp_path / "home", ())
    first = candidate(ancestor / "a")
    candidate(home / "home-workspace")
    monkeypatch.setattr(locator, "search_bases", lambda cwd, home: [cwd, ancestor, home])
    assert locate_workspace(cwd=cwd, home=home, env={}) == first
    for path in first.iterdir():
        path.unlink()
    assert locate_workspace(cwd=cwd, home=home, env={}) == home / "home-workspace"


def test_deployment_example_and_no_grandchildren(tmp_path: Path) -> None:
    workspace = candidate(tmp_path / "ddns-config")
    candidate(tmp_path / "dnsleaf-backups" / "backup-2026-09-17")
    assert locate_workspace(cwd=tmp_path, env={}) == workspace
    for file in workspace.iterdir():
        file.unlink()
    with pytest.raises(WorkspaceNotFoundError) as caught:
        locate_workspace(cwd=tmp_path, env={})
    assert "backup-2026-09-17" not in str(caught.value)


def test_complete_invalid_candidate_is_selected_and_loading_fails(tmp_path: Path) -> None:
    bad = candidate(tmp_path / "a")
    (bad / "workspace.yaml").write_text("zone_name: [\n")
    candidate(tmp_path / "b")
    root = locate_workspace(cwd=tmp_path, env={})
    assert root == bad
    with pytest.raises(WorkspaceLoadError, match=r"workspace.yaml.*line 2, column 1"):
        WorkspaceStorage().load(root)


@pytest.mark.parametrize("kind", ["directory", "fifo", "dangling"])
def test_invalid_file_types_block_fallback(tmp_path: Path, kind: str) -> None:
    bad = candidate(tmp_path / "a", ("entries.yaml",))
    path = bad / "workspace.yaml"
    if kind == "directory":
        path.mkdir()
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.symlink_to(bad / "missing")
    candidate(tmp_path / "b")
    with pytest.raises(OSError, match=str(path)):
        locate_workspace(cwd=tmp_path, env={})


def test_permission_and_enumeration_errors_block_search(tmp_path: Path, monkeypatch) -> None:
    candidate(tmp_path / "a")
    candidate(tmp_path / "b")
    original = check_regular_readable_file

    def denied(path: Path) -> None:
        if path.parent.name == "a":
            raise PermissionError(f"cannot read {path}")
        original(path)

    monkeypatch.setattr(locator, "check_regular_readable_file", denied)
    with pytest.raises(PermissionError, match="cannot read"):
        locate_workspace(cwd=tmp_path, env={})
    monkeypatch.setattr(Path, "iterdir", Mock(side_effect=PermissionError("cannot enumerate")))
    with pytest.raises(PermissionError, match="cannot enumerate"):
        locate_workspace(cwd=tmp_path, env={})


def test_symlink_candidates_and_duplicate_resolved_paths(tmp_path: Path, monkeypatch) -> None:
    root = candidate(tmp_path / "base", ())
    target = candidate(tmp_path / "elsewhere", ("workspace.yaml",))
    (root / "a").symlink_to(target, target_is_directory=True)
    (root / "b").symlink_to(target, target_is_directory=True)
    calls = Mock(wraps=locator.missing_source_files)
    monkeypatch.setattr(locator, "missing_source_files", calls)
    with pytest.raises(WorkspaceNotFoundError) as caught:
        locate_workspace(cwd=root, env={})
    assert len(caught.value.incomplete) == 1
    assert calls.call_count == 2  # resolved target and base
    (target / "entries.yaml").write_text("entries: []\n")
    assert locate_workspace(cwd=root, env={}) == target


def test_selected_file_disappearance_is_fatal(tmp_path: Path) -> None:
    selected = candidate(tmp_path / "a")
    candidate(tmp_path / "b")
    root = locate_workspace(cwd=tmp_path, env={})
    (selected / "entries.yaml").unlink()
    with pytest.raises(WorkspaceLoadError, match="workspace file not found"):
        WorkspaceStorage().load(root)


def test_unselected_child_disappearance_is_ignored(tmp_path: Path, monkeypatch) -> None:
    vanished = candidate(tmp_path / "a", ())
    complete = candidate(tmp_path / "b")
    original = Path.stat

    def racing_stat(path: Path, *args, **kwargs):
        if path == vanished:
            raise FileNotFoundError(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", racing_stat)
    assert locate_workspace(cwd=tmp_path, env={}) == complete


def test_file_replaced_by_fifo_before_open_is_rejected(tmp_path: Path, monkeypatch) -> None:
    from dnsleaf.config.resources import read_yaml_mapping

    path = tmp_path / "workspace.yaml"
    path.write_text("{}")
    original = os.open

    def replace_then_open(name, flags):
        path.unlink()
        os.mkfifo(path)
        return original(name, flags)

    monkeypatch.setattr("dnsleaf.config.resources.os.open", replace_then_open)
    with pytest.raises(OSError, match="not a regular file"):
        read_yaml_mapping(path)
