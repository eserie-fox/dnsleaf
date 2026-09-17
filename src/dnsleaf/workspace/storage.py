"""Workspace storage and scaffolding helpers."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dnsleaf.config.resources import read_yaml_mapping
from dnsleaf.config.scaffold import load_scaffold_layout, load_scaffold_secrets_readme
from dnsleaf.dns.cloudflare import CloudflareConfigurationError
from dnsleaf.workspace.models import (
    EntriesFile,
    ManagedRecordFile,
    ResolvedWorkspace,
    WorkspaceConfig,
    WorkspaceEntry,
)


class WorkspaceError(RuntimeError):
    """Base exception for workspace loading and writing failures."""


class WorkspaceInitError(WorkspaceError):
    """Raised when workspace scaffolding cannot proceed."""


class WorkspaceLoadError(WorkspaceError):
    """Raised when a workspace file cannot be loaded."""


class WorkspaceValidationError(WorkspaceError):
    """Raised when a workspace cannot be validated."""


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Resolved workspace filesystem layout."""

    root: Path

    @property
    def workspace_file(self) -> Path:
        return self.root / "workspace.yaml"

    @property
    def entries_file(self) -> Path:
        return self.root / "entries.yaml"

    @property
    def secrets_dir(self) -> Path:
        return self.root / "secrets"

    @property
    def rendered_dir(self) -> Path:
        return self.root / "rendered"

    @property
    def effective_workspace_file(self) -> Path:
        return self.rendered_dir / "effective-workspace.json"

    @property
    def desired_records_file(self) -> Path:
        return self.rendered_dir / "desired-records.json"

    @property
    def rendered_systemd_dir(self) -> Path:
        return self.rendered_dir / "systemd"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def runtime_logs_dir(self) -> Path:
        return self.runtime_dir / "logs"

    @property
    def runtime_run_dir(self) -> Path:
        return self.runtime_dir / "run"

    @property
    def runtime_log_file(self) -> Path:
        return self.runtime_logs_dir / "dnsleaf.log"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def last_apply_file(self) -> Path:
        return self.state_dir / "last-apply.json"

    @property
    def managed_records_file(self) -> Path:
        return self.state_dir / "managed-records.json"


@dataclass(slots=True)
class LoadedWorkspace:
    """Loaded workspace source config and resolved runtime view."""

    paths: WorkspacePaths
    workspace_config: WorkspaceConfig
    resolved_workspace: ResolvedWorkspace
    entries_file: EntriesFile

    def enabled_entries(self) -> list[WorkspaceEntry]:
        """Return enabled entries only."""

        return self.entries_file.enabled_entries()


class WorkspaceStorage:
    """Load and scaffold workspace files."""

    def paths_for(self, workspace_dir: str | Path) -> WorkspacePaths:
        """Return resolved paths for a workspace root."""

        return WorkspacePaths(root=Path(workspace_dir).expanduser().resolve())

    def scaffold(self, workspace_dir: str | Path) -> WorkspacePaths:
        """Create a new workspace directory and starter files."""

        paths = self.paths_for(workspace_dir)
        if paths.root.exists():
            if not paths.root.is_dir():
                raise WorkspaceInitError(
                    f"workspace path exists and is not a directory: {paths.root}"
                )
            if any(paths.root.iterdir()):
                raise WorkspaceInitError(
                    f"workspace directory already exists and is not empty: {paths.root}"
                )
        else:
            paths.root.mkdir(parents=True, exist_ok=False)

        for directory in load_scaffold_layout().directories:
            (paths.root / directory).mkdir(parents=True, exist_ok=True)

        workspace_config = WorkspaceConfig.scaffold_defaults(paths.root.name)
        entries_file = EntriesFile.scaffold_defaults()
        workspace_payload = workspace_config.model_dump(mode="json", exclude_none=True)
        workspace_payload["default_proxied"] = workspace_config.default_proxied
        dump_yaml_data(
            paths.workspace_file,
            workspace_payload,
        )
        dump_yaml_data(paths.entries_file, entries_file.model_dump(mode="json", exclude_none=True))
        atomic_write_text(
            paths.secrets_dir / "README.txt",
            load_scaffold_secrets_readme(),
        )
        dump_json_data(
            paths.managed_records_file,
            ManagedRecordFile().model_dump(mode="json"),
        )
        return paths

    def load(self, workspace_dir: str | Path) -> LoadedWorkspace:
        """Load workspace source files without runtime-only checks."""

        paths = self.paths_for(workspace_dir)
        try:
            workspace_config = WorkspaceConfig.from_mapping(load_yaml_mapping(paths.workspace_file))
            resolved_workspace = workspace_config.resolve(paths.root)
        except (ValueError, OSError, WorkspaceLoadError) as exc:
            raise WorkspaceLoadError(
                f"workspace {paths.root}, file {paths.workspace_file}: {exc}"
            ) from exc
        try:
            entries_file = EntriesFile.from_mapping(load_yaml_mapping(paths.entries_file))
        except (ValueError, OSError, WorkspaceLoadError) as exc:
            raise WorkspaceLoadError(
                f"workspace {paths.root}, file {paths.entries_file}: {exc}"
            ) from exc
        return LoadedWorkspace(
            paths=paths,
            workspace_config=workspace_config,
            resolved_workspace=resolved_workspace,
            entries_file=entries_file,
        )

    def validate(self, workspace_dir: str | Path) -> LoadedWorkspace:
        """Load a workspace and validate runtime-resolved references."""

        loaded = self.load(workspace_dir)
        return self.validate_loaded(loaded)

    def validate_loaded(self, loaded: LoadedWorkspace) -> LoadedWorkspace:
        """Validate runtime-resolved references for a previously loaded workspace."""

        provider_config = loaded.resolved_workspace.cloudflare_provider_config()
        try:
            provider_config.resolved_api_token()
        except CloudflareConfigurationError as exc:
            raise WorkspaceLoadError(
                f"workspace {loaded.paths.root}, file {loaded.paths.workspace_file}, "
                f"api_token_file: {exc}"
            ) from exc
        return loaded


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file and require a mapping payload."""

    try:
        return read_yaml_mapping(path)
    except FileNotFoundError as exc:
        raise WorkspaceLoadError(f"workspace file not found: {path}") from exc
    except OSError as exc:
        raise WorkspaceLoadError(f"failed to read workspace file {path}: {exc}") from exc
    except ValueError as exc:
        raise WorkspaceLoadError(str(exc)) from exc


def dump_yaml_data(path: Path, data: Mapping[str, Any]) -> None:
    """Write YAML data atomically."""

    content = yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=False)
    atomic_write_text(path, content)


def dump_json_data(path: Path, data: Any) -> None:
    """Write JSON data atomically."""

    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via a temporary file and replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def ensure_writable_directory(path: Path) -> None:
    """Check state persistence before any remote writes or system installation."""

    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path):
        pass
