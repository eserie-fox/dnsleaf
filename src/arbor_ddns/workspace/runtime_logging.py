"""Workspace-local runtime logging helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from arbor_ddns.workspace.storage import WorkspacePaths


def workspace_command_logger(
    paths: WorkspacePaths,
    *,
    workspace_name: str,
    command_name: str,
) -> logging.LoggerAdapter[logging.Logger]:
    """Return a file-backed logger for one workspace command."""

    log_file = paths.runtime_log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger_name = f"arbor_ddns.workspace.{str(log_file.resolve())}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not _has_file_handler(logger, log_file):
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s level=%(levelname)s "
                "workspace=%(workspace_name)s command=%(command_name)s %(message)s"
            )
        )
        logger.addHandler(handler)

    return logging.LoggerAdapter(
        logger,
        {"workspace_name": workspace_name, "command_name": command_name},
    )


def close_workspace_logger(logger: logging.LoggerAdapter[logging.Logger]) -> None:
    """Close and detach file handlers for a workspace logger."""

    base_logger = logger.logger
    for handler in list(base_logger.handlers):
        handler.flush()
        handler.close()
        base_logger.removeHandler(handler)


def _has_file_handler(logger: logging.Logger, log_file: Path) -> bool:
    resolved = str(log_file.resolve())
    for handler in logger.handlers:
        if not isinstance(handler, logging.FileHandler):
            continue
        if Path(handler.baseFilename).resolve() == Path(resolved):
            return True
    return False
