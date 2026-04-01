"""Runtime logging configuration and workspace-scoped logging contexts."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from arbor_ddns.logging.config import (
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL_NAME,
    DEFAULT_RETENTION_DAYS,
    LoggingStream,
    normalize_log_level_name,
    resolved_log_level,
)

if TYPE_CHECKING:
    from arbor_ddns.workspace.storage import LoadedWorkspace

_DEFAULT_CONTEXT_FIELDS: dict[str, object] = {
    "workspace_name": "-",
    "command_name": "-",
}


class DailySymlinkFileHandler(logging.Handler):
    """Write logs to daily files and keep a stable symlink to the latest file."""

    def __init__(
        self,
        symlink_path: str | Path,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        encoding: str = "utf-8",
        now_func: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        super().__init__()
        path = Path(symlink_path).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()

        self.symlink_path = path
        self.log_dir = path.parent
        self.stem = path.stem
        self.retention_days = max(1, retention_days)
        self.encoding = encoding
        self._now = now_func
        self._lock = threading.RLock()
        self._current_date: str | None = None
        self._file_handler: logging.FileHandler | None = None

    @property
    def current_log_path(self) -> Path | None:
        """Return the current dated log file, if one has been opened."""

        if self._file_handler is None:
            return None
        return Path(self._file_handler.baseFilename)

    def setFormatter(self, fmt: logging.Formatter | None) -> None:  # noqa: N802
        super().setFormatter(fmt)
        if self._file_handler is not None:
            self._file_handler.setFormatter(fmt)

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._rotate_if_needed()
            if self._file_handler is not None:
                self._file_handler.emit(record)

    def flush(self) -> None:
        with self._lock:
            if self._file_handler is not None:
                self._file_handler.flush()

    def close(self) -> None:
        with self._lock:
            if self._file_handler is not None:
                self._file_handler.close()
                self._file_handler = None
        super().close()

    def _rotate_if_needed(self) -> None:
        today = self._now().astimezone(UTC).strftime("%Y-%m-%d")
        if self._current_date == today and self._file_handler is not None:
            return

        if self._file_handler is not None:
            self._file_handler.close()

        self.log_dir.mkdir(parents=True, exist_ok=True)
        daily_file = self.log_dir / f"{self.stem}-{today}.log"
        self._file_handler = logging.FileHandler(daily_file, encoding=self.encoding)
        if self.formatter is not None:
            self._file_handler.setFormatter(self.formatter)
        for current_filter in self.filters:
            self._file_handler.addFilter(current_filter)

        self._current_date = today
        _cleanup_old_logs(
            self.log_dir,
            stem=self.stem,
            retention_days=self.retention_days,
            keep_file=daily_file,
            now_func=self._now,
        )
        _update_symlink(self.symlink_path, daily_file)


@dataclass(slots=True)
class _RootLoggerState:
    level: int
    handlers: list[logging.Handler]


@dataclass(slots=True, frozen=True)
class ResolvedLoggingConfig:
    """Apply-ready runtime logging configuration."""

    level: int
    format: str
    file_path: Path | None
    retention_days: int
    stream: LoggingStream


class _ContextDefaultsFilter(logging.Filter):
    """Inject stable context fields so format strings remain safe."""

    def __init__(self, context_fields: dict[str, object] | None = None) -> None:
        super().__init__()
        self._context_fields = {**_DEFAULT_CONTEXT_FIELDS, **(context_fields or {})}

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self._context_fields.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True

def configure_default_logging(
    *,
    stream_name: LoggingStream = "stderr",
    level: int = logging.INFO,
    fmt: str = DEFAULT_LOG_FORMAT,
) -> None:
    """Configure simple root logging for non-workspace commands."""

    apply_logging_config(
        ResolvedLoggingConfig(
            level=level,
            format=fmt,
            file_path=None,
            retention_days=DEFAULT_RETENTION_DAYS,
            stream=stream_name,
        ),
        close_existing=True,
    )


def load_workspace_logging_config(
    workspace_dir: Path,
    *,
    loaded_workspace: LoadedWorkspace | None = None,
) -> tuple[LoadedWorkspace, ResolvedLoggingConfig]:
    """Load one workspace's resolved logging config without mutating the root logger."""

    if loaded_workspace is None:
        from arbor_ddns.workspace.storage import WorkspaceStorage

        loaded_workspace = WorkspaceStorage().load(workspace_dir)

    logging_config = loaded_workspace.resolved_workspace.arbor_ddns_logging
    file_path = (
        Path(logging_config.file_path).resolve() if logging_config.file_path is not None else None
    )
    return loaded_workspace, ResolvedLoggingConfig(
        level=resolved_log_level(logging_config.level),
        format=logging_config.format,
        file_path=file_path,
        retention_days=logging_config.retention_days,
        stream=logging_config.stream,
    )


@contextmanager
def workspace_logging_context(
    workspace_dir: Path,
    *,
    command_name: str,
    loaded_workspace: LoadedWorkspace | None = None,
) -> Iterator[LoadedWorkspace]:
    """Temporarily apply one workspace's logging configuration."""

    resolved_workspace, config = load_workspace_logging_config(
        workspace_dir,
        loaded_workspace=loaded_workspace,
    )
    snapshot = _capture_root_logger()
    try:
        apply_logging_config(
            config,
            close_existing=False,
            context_fields={
                "workspace_name": resolved_workspace.resolved_workspace.workspace_name,
                "command_name": command_name,
            },
        )
        yield resolved_workspace
    finally:
        _restore_root_logger(snapshot)


def apply_logging_config(
    config: ResolvedLoggingConfig,
    *,
    close_existing: bool,
    context_fields: dict[str, object] | None = None,
) -> Path | None:
    """Replace root logger handlers with one already-resolved configuration."""

    formatter = logging.Formatter(config.format)
    enrich_filter = _ContextDefaultsFilter(context_fields)
    handlers: list[logging.Handler] = []
    log_path = config.file_path

    if log_path is not None:
        file_handler = DailySymlinkFileHandler(
            log_path,
            retention_days=config.retention_days,
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(enrich_filter)
        handlers.append(file_handler)

    if config.stream == "stdout":
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(enrich_filter)
        handlers.append(stream_handler)
    elif config.stream == "stderr":
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(enrich_filter)
        handlers.append(stream_handler)
    if not handlers:
        null_handler = logging.NullHandler()
        null_handler.addFilter(enrich_filter)
        handlers.append(null_handler)

    _replace_root_logger_handlers(
        level=config.level,
        handlers=handlers,
        close_existing=close_existing,
    )
    return log_path


def _capture_root_logger() -> _RootLoggerState:
    root_logger = logging.getLogger()
    return _RootLoggerState(level=root_logger.level, handlers=list(root_logger.handlers))


def _restore_root_logger(state: _RootLoggerState) -> None:
    _replace_root_logger_handlers(
        level=state.level,
        handlers=state.handlers,
        close_existing=True,
        preserved_handlers=state.handlers,
    )


def _replace_root_logger_handlers(
    *,
    level: int,
    handlers: list[logging.Handler],
    close_existing: bool,
    preserved_handlers: list[logging.Handler] | None = None,
) -> None:
    root_logger = logging.getLogger()
    preserved = set(preserved_handlers or [])
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        if close_existing and handler not in preserved:
            handler.close()
    root_logger.setLevel(level)
    for handler in handlers:
        root_logger.addHandler(handler)


def _cleanup_old_logs(
    log_dir: Path,
    *,
    stem: str,
    retention_days: int,
    keep_file: Path,
    now_func: Callable[[], datetime],
) -> None:
    cutoff = now_func().astimezone(UTC).date() - timedelta(days=max(1, retention_days) - 1)

    for candidate in log_dir.glob(f"{stem}-*.log"):
        if candidate == keep_file:
            continue

        suffix = candidate.stem[len(stem) + 1 :]
        try:
            candidate_date = datetime.strptime(suffix, "%Y-%m-%d").date()
        except ValueError:
            continue

        if candidate_date < cutoff:
            candidate.unlink(missing_ok=True)


def _update_symlink(link_path: Path, current_file: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.symlink_to(current_file)


__all__ = [
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_LOG_LEVEL_NAME",
    "DEFAULT_RETENTION_DAYS",
    "DailySymlinkFileHandler",
    "LoggingStream",
    "ResolvedLoggingConfig",
    "apply_logging_config",
    "configure_default_logging",
    "load_workspace_logging_config",
    "normalize_log_level_name",
    "resolved_log_level",
    "workspace_logging_context",
]
