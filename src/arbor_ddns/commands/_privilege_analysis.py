"""Privilege requirement analysis for CLI commands."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from arbor_ddns.models import EntrySourceKind, TargetKind
from arbor_ddns.util.process import command_available
from arbor_ddns.workspace.storage import LoadedWorkspace, WorkspacePaths, WorkspaceStorage


@dataclass(slots=True)
class WorkspacePrivilegeProbe:
    """Workspace paths, loaded config, and discovered privilege reasons."""

    paths: WorkspacePaths
    loaded: LoadedWorkspace | None
    reasons: list[str]


def can_read_directory(path: Path) -> bool:
    """Return whether the current user can read and traverse a directory."""

    return path.is_dir() and os.access(path, os.R_OK | os.X_OK)


def can_read_file(path: Path) -> bool:
    """Return whether the current user can read a file."""

    return path.exists() and path.is_file() and os.access(path, os.R_OK)


def can_write_directory(path: Path) -> bool:
    """Return whether the current user can create or update entries under one directory."""

    if path.exists():
        return path.is_dir() and _has_write_execute(path)
    return _has_write_execute(_nearest_existing_parent(path))


def can_write_file(path: Path) -> bool:
    """Return whether the current user can write to one file target."""

    if path.exists():
        return os.access(path, os.W_OK)
    return _has_write_execute(_nearest_existing_parent(path.parent))


def can_delete_path(path: Path) -> bool:
    """Return whether the current user can delete one file or directory path."""

    if not path.exists():
        return True
    resolved = path.resolve()
    if resolved.is_dir() and not resolved.is_symlink():
        return _has_write_execute(resolved.parent) and _has_write_execute(resolved)
    return _has_write_execute(resolved.parent)


def root_owned_hint(path: Path) -> str:
    """Return a short ownership hint for root-owned existing paths."""

    try:
        owner_uid = path.stat(follow_symlinks=False).st_uid
    except OSError:
        return ""
    if owner_uid == 0:
        return " (existing target is owned by root)"
    return ""


def analyze_init_root_requirements(directory: Path) -> list[str]:
    """Return reasons why `init` needs root privileges."""

    target = directory.expanduser().resolve()
    reasons: list[str] = []
    if target.exists():
        if not can_write_directory(target):
            _append_reason(
                reasons,
                "workspace directory is not writable by current user: "
                f"{target}{root_owned_hint(target)}",
            )
        return reasons

    parent = _nearest_existing_parent(target.parent)
    if not _has_write_execute(parent):
        _append_reason(
            reasons,
            f"cannot create workspace under {parent}{root_owned_hint(parent)}",
        )
    return reasons


def analyze_entry_list_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why `entry list` needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
    return probe.reasons


def analyze_entry_write_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why an entry mutation needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    if probe.paths.entries_file.exists() and not can_write_file(probe.paths.entries_file):
        _append_reason(
            probe.reasons,
            "entries file is not writable by current user: "
            f"{probe.paths.entries_file}{root_owned_hint(probe.paths.entries_file)}",
        )
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
    return probe.reasons


def analyze_validate_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why `validate` needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    _append_token_read_reason(probe)
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
    return probe.reasons


def analyze_render_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why `render` needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    if not can_write_directory(probe.paths.rendered_dir):
        _append_reason(
            probe.reasons,
            "rendered output path is not writable by current user: "
            f"{probe.paths.rendered_dir}{root_owned_hint(probe.paths.rendered_dir)}",
        )
    if not can_write_directory(probe.paths.rendered_systemd_dir):
        _append_reason(
            probe.reasons,
            "rendered systemd path is not writable by current user: "
            f"{probe.paths.rendered_systemd_dir}"
            f"{root_owned_hint(probe.paths.rendered_systemd_dir)}",
        )
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
    return probe.reasons


def analyze_plan_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why `plan` needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    _append_token_read_reason(probe)
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
        _append_dynamic_discovery_reasons(probe.reasons, probe.loaded)
    return probe.reasons


def analyze_sync_once_root_requirements(workspace: Path, *, apply: bool) -> list[str]:
    """Return reasons why `sync-once` needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    _append_token_read_reason(probe)
    if apply and not can_write_directory(probe.paths.state_dir):
        _append_reason(
            probe.reasons,
            "state path is not writable by current user: "
            f"{probe.paths.state_dir}{root_owned_hint(probe.paths.state_dir)}",
        )
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
        _append_dynamic_discovery_reasons(probe.reasons, probe.loaded)
    return probe.reasons


def analyze_apply_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why `apply` needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    _append_token_read_reason(probe)
    if not can_write_directory(probe.paths.rendered_dir):
        _append_reason(
            probe.reasons,
            "rendered output path is not writable by current user: "
            f"{probe.paths.rendered_dir}{root_owned_hint(probe.paths.rendered_dir)}",
        )
    if not can_write_directory(probe.paths.rendered_systemd_dir):
        _append_reason(
            probe.reasons,
            "rendered systemd path is not writable by current user: "
            f"{probe.paths.rendered_systemd_dir}"
            f"{root_owned_hint(probe.paths.rendered_systemd_dir)}",
        )
    if not can_write_directory(probe.paths.state_dir):
        _append_reason(
            probe.reasons,
            "state path is not writable by current user: "
            f"{probe.paths.state_dir}{root_owned_hint(probe.paths.state_dir)}",
        )
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
        unit_dir = probe.loaded.resolved_workspace.paths.resolved_systemd_unit_dir()
        if not can_write_directory(unit_dir):
            _append_reason(
                probe.reasons,
                "systemd unit directory is not writable by current user: "
                f"{unit_dir}{root_owned_hint(unit_dir)}",
            )
        _append_reason(probe.reasons, "will manage system services via systemctl")
        _append_dynamic_discovery_reasons(probe.reasons, probe.loaded)
    else:
        _append_reason(probe.reasons, "will manage system services via systemctl")
    return probe.reasons


def analyze_uninstall_root_requirements(workspace: Path, *, purge: bool) -> list[str]:
    """Return reasons why `uninstall` needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
        systemctl_bin = probe.loaded.resolved_workspace.paths.systemctl_bin
        if command_available(systemctl_bin):
            _append_reason(probe.reasons, "will manage system services via systemctl")
        for unit_kind in ("service", "timer"):
            unit_name = getattr(probe.loaded.resolved_workspace.systemd, unit_kind + "_name")
            unit_path = (
                probe.loaded.resolved_workspace.paths.resolved_systemd_unit_dir()
                / f"{unit_name}.{unit_kind}"
            )
            if unit_path.exists() and not can_delete_path(unit_path):
                _append_reason(
                    probe.reasons,
                    f"installed {unit_kind} unit is not removable by current user: "
                    f"{unit_path}{root_owned_hint(unit_path)}",
                )
    for target in (probe.paths.rendered_dir, probe.paths.runtime_dir):
        if target.exists() and not can_delete_path(target):
            _append_reason(
                probe.reasons,
                "generated path is not removable by current user: "
                f"{target}{root_owned_hint(target)}",
            )
    if purge and probe.paths.root.exists() and not can_delete_path(probe.paths.root):
        _append_reason(
            probe.reasons,
            "workspace root is not removable by current user: "
            f"{probe.paths.root}{root_owned_hint(probe.paths.root)}",
        )
    return probe.reasons


def analyze_status_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why `status` needs root privileges."""

    return _probe_workspace(workspace, need_entries=True).reasons


def analyze_doctor_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why `doctor` needs root privileges."""

    return _probe_workspace(workspace, need_entries=True).reasons


def analyze_provider_verify_root_requirements(workspace: Path) -> list[str]:
    """Return reasons why `provider verify` needs root privileges."""

    probe = _probe_workspace(workspace, need_entries=True)
    _append_token_read_reason(probe)
    if probe.loaded is not None:
        _append_log_write_reason(probe.reasons, probe.loaded)
    return probe.reasons


def analyze_discover_root_requirements(
    kind: TargetKind,
    *,
    workspace: Path | None,
) -> list[str]:
    """Return reasons why `discover` needs root privileges."""

    reasons: list[str] = []
    probe = _discover_workspace_probe(workspace)
    reasons.extend(probe.reasons)
    if probe.loaded is not None:
        _append_log_write_reason(reasons, probe.loaded)
    if kind is TargetKind.LXC:
        _append_reason(reasons, "will execute PVE guest discovery via pct exec")
    elif kind is TargetKind.VM:
        _append_reason(reasons, "will execute PVE guest discovery via qm agent")
    return reasons


def _probe_workspace(workspace: Path, *, need_entries: bool) -> WorkspacePrivilegeProbe:
    storage = WorkspaceStorage()
    paths = storage.paths_for(workspace)
    reasons: list[str] = []

    parent = _nearest_existing_parent(paths.root.parent)
    if parent.exists() and not can_read_directory(parent):
        _append_reason(
            reasons,
            "workspace parent directory is not readable by current user: "
            f"{parent}{root_owned_hint(parent)}",
        )
    if paths.root.exists() and not can_read_directory(paths.root):
        _append_reason(
            reasons,
            "workspace root is not readable by current user: "
            f"{paths.root}{root_owned_hint(paths.root)}",
        )
    if paths.workspace_file.exists() and not can_read_file(paths.workspace_file):
        _append_reason(
            reasons,
            "workspace config is not readable by current user: "
            f"{paths.workspace_file}{root_owned_hint(paths.workspace_file)}",
        )
    if need_entries and paths.entries_file.exists() and not can_read_file(paths.entries_file):
        _append_reason(
            reasons,
            "entries file is not readable by current user: "
            f"{paths.entries_file}{root_owned_hint(paths.entries_file)}",
        )

    loaded: LoadedWorkspace | None = None
    if not reasons:
        try:
            loaded = storage.load(paths.root)
        except Exception:
            loaded = None
    return WorkspacePrivilegeProbe(paths=paths, loaded=loaded, reasons=reasons)


def _discover_workspace_probe(workspace: Path | None) -> WorkspacePrivilegeProbe:
    if workspace is not None:
        return _probe_workspace(workspace, need_entries=False)

    candidate = Path(".")
    workspace_file = candidate / "workspace.yaml"
    if not workspace_file.exists():
        storage = WorkspaceStorage()
        return WorkspacePrivilegeProbe(paths=storage.paths_for(candidate), loaded=None, reasons=[])
    return _probe_workspace(candidate, need_entries=False)


def _append_token_read_reason(probe: WorkspacePrivilegeProbe) -> None:
    if probe.loaded is None:
        return
    token_path = Path(probe.loaded.resolved_workspace.api_token_file)
    if token_path.exists() and not can_read_file(token_path):
        _append_reason(
            probe.reasons,
            "token file is not readable by current user: "
            f"{token_path}{root_owned_hint(token_path)}",
        )


def _append_log_write_reason(reasons: list[str], loaded: LoadedWorkspace) -> None:
    log_path = loaded.resolved_workspace.arbor_ddns_logging.resolved_file_path()
    if log_path is None:
        return
    if can_write_file(log_path):
        return
    _append_reason(
        reasons,
        "workspace runtime log path is not writable by current user: "
        f"{log_path}{root_owned_hint(log_path)}",
    )


def _append_dynamic_discovery_reasons(reasons: list[str], loaded: LoadedWorkspace) -> None:
    enabled_entries = loaded.entries_file.enabled_entries()
    if any(entry.source_kind is EntrySourceKind.LXC for entry in enabled_entries):
        _append_reason(reasons, "will execute PVE guest discovery via pct exec")
    if any(entry.source_kind is EntrySourceKind.VM for entry in enabled_entries):
        _append_reason(reasons, "will execute PVE guest discovery via qm agent")


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _nearest_existing_parent(path: Path) -> Path:
    probe = path.resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def _has_write_execute(path: Path) -> bool:
    return os.access(path, os.W_OK | os.X_OK)
