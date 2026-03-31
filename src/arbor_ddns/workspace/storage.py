"""Workspace storage and scaffolding helpers."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from arbor_ddns.config import AppConfig
from arbor_ddns.workspace.models import (
    EntriesFile,
    ManagedRecordFile,
    ResolvedWorkspace,
    WorkspaceApplyConfig,
    WorkspaceConfig,
    WorkspaceEntry,
    WorkspaceSystemdConfig,
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
        return self.runtime_logs_dir / "arbor-ddns.log"

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

    app_config: AppConfig
    paths: WorkspacePaths
    workspace_config: WorkspaceConfig
    resolved_workspace: ResolvedWorkspace
    entries_file: EntriesFile

    def enabled_entries(self) -> list[WorkspaceEntry]:
        """Return enabled entries only."""

        return self.entries_file.enabled_entries()


class WorkspaceStorage:
    """Load and scaffold workspace files."""

    def __init__(self, app_config: AppConfig | None = None) -> None:
        self._app_config = app_config or AppConfig.from_defaults()

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

        paths.secrets_dir.mkdir(parents=True, exist_ok=True)
        paths.rendered_systemd_dir.mkdir(parents=True, exist_ok=True)
        paths.runtime_logs_dir.mkdir(parents=True, exist_ok=True)
        paths.runtime_run_dir.mkdir(parents=True, exist_ok=True)
        paths.state_dir.mkdir(parents=True, exist_ok=True)

        scaffold = self._app_config.workspace_scaffold
        workspace_config = WorkspaceConfig(
            config_version=scaffold.config_version,
            workspace_name=paths.root.name,
            provider=scaffold.provider,
            zone_name=scaffold.zone_name,
            zone_id=scaffold.zone_id,
            api_token_file=scaffold.api_token_file,
            default_ttl=scaffold.default_ttl,
            default_proxied=scaffold.default_proxied,
            systemd=WorkspaceSystemdConfig(
                service_name=None,
                timer_name=None,
                on_boot_sec=scaffold.systemd.on_boot_sec,
                on_unit_active_sec=scaffold.systemd.on_unit_active_sec,
                run_sync_after_apply=scaffold.systemd.run_sync_after_apply,
            ),
            apply=WorkspaceApplyConfig(
                prune_managed_records=scaffold.apply.prune_managed_records,
            ),
        )
        entries_file = EntriesFile(config_version=2, entries=[])
        dump_yaml_data(
            paths.workspace_file,
            workspace_config.model_dump(mode="json", exclude_none=True),
        )
        dump_yaml_data(paths.entries_file, entries_file.model_dump(mode="json", exclude_none=True))
        atomic_write_text(
            paths.secrets_dir / "README.txt",
            (
                "Place secret material in this directory.\n\n"
                "Recommended layout:\n"
                "- secrets/cloudflare_api_token.txt\n\n"
                "Do not commit real secrets to version control.\n"
            ),
        )
        dump_json_data(
            paths.managed_records_file,
            ManagedRecordFile().model_dump(mode="json"),
        )
        return paths

    def load(self, workspace_dir: str | Path) -> LoadedWorkspace:
        """Load workspace source files without runtime-only checks."""

        paths = self.paths_for(workspace_dir)
        workspace_payload = load_yaml_mapping(paths.workspace_file)
        entries_payload = load_yaml_mapping(paths.entries_file)
        workspace_config = WorkspaceConfig.model_validate(workspace_payload)
        entries_file = EntriesFile.model_validate(entries_payload)
        resolved_workspace = workspace_config.resolve(paths.root)
        return LoadedWorkspace(
            app_config=self._app_config,
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
        provider_config.resolved_api_token()
        return loaded


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file and require a mapping payload."""

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise WorkspaceLoadError(f"workspace file not found: {path}") from exc
    except OSError as exc:
        raise WorkspaceLoadError(f"failed to read workspace file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise WorkspaceLoadError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise WorkspaceLoadError(f"expected mapping content in {path}")
    return dict(payload)


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
