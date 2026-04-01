from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from arbor_ddns.logging import (
    DailySymlinkFileHandler,
    ResolvedLoggingConfig,
    apply_logging_config,
    configure_default_logging,
    load_workspace_logging_config,
    workspace_logging_context,
)
from arbor_ddns.logging import (
    runtime as logging_runtime,
)
from arbor_ddns.logging.config import absolute_path_without_symlink_resolution
from arbor_ddns.workspace.service import WorkspaceService
from arbor_ddns.workspace.storage import WorkspaceLoadError


@contextmanager
def _restore_root_logger():
    root = logging.getLogger()
    level = root.level
    handlers = list(root.handlers)
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            if handler not in handlers:
                handler.close()
        root.setLevel(level)
        for handler in handlers:
            root.addHandler(handler)


def _write_workspace_logging_override(
    workspace: Path,
    *,
    file_path: str,
    stream: str = "none",
) -> None:
    payload = yaml.safe_load((workspace / "workspace.yaml").read_text(encoding="utf-8"))
    payload["arbor_ddns_logging"]["file_path"] = file_path
    payload["arbor_ddns_logging"]["stream"] = stream
    (workspace / "workspace.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def test_daily_symlink_handler_is_lazy_until_first_record(tmp_path: Path) -> None:
    current = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

    def now() -> datetime:
        return current

    handler = DailySymlinkFileHandler(tmp_path / "arbor-ddns.log", now_func=now)

    assert not (tmp_path / "arbor-ddns.log").exists()
    assert not any(tmp_path.iterdir())

    record = logging.makeLogRecord(
        {
            "name": "arbor_ddns.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "hello world",
        }
    )
    handler.emit(record)
    handler.close()

    symlink = tmp_path / "arbor-ddns.log"
    daily_file = tmp_path / "arbor-ddns-2026-04-01.log"
    assert symlink.is_symlink()
    assert symlink.resolve() == daily_file.resolve()
    assert "hello world" in daily_file.read_text(encoding="utf-8")


def test_daily_symlink_handler_prunes_old_files_by_retention(tmp_path: Path) -> None:
    current = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

    def now() -> datetime:
        return current

    old_file = tmp_path / "arbor-ddns-2026-03-29.log"
    keep_file = tmp_path / "arbor-ddns-2026-03-31.log"
    old_file.write_text("old", encoding="utf-8")
    keep_file.write_text("keep", encoding="utf-8")

    handler = DailySymlinkFileHandler(
        tmp_path / "arbor-ddns.log",
        retention_days=2,
        now_func=now,
    )
    handler.emit(
        logging.makeLogRecord(
            {
                "name": "arbor_ddns.test",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "msg": "rotate",
            }
        )
    )
    handler.close()

    assert not old_file.exists()
    assert keep_file.exists()
    assert (tmp_path / "arbor-ddns-2026-04-01.log").exists()


def test_configure_default_logging_uses_stderr_by_default(capsys) -> None:
    with _restore_root_logger():
        configure_default_logging()
        logging.getLogger("arbor_ddns.test").warning("default logging active")

    captured = capsys.readouterr()
    assert "default logging active" in captured.err


def test_load_workspace_logging_config_returns_resolved_config_without_mutating_root_logger(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "lab"
    WorkspaceService().init_workspace(workspace)
    _write_workspace_logging_override(workspace, file_path="state/logs/custom.log")
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)

    loaded, config = load_workspace_logging_config(workspace)

    assert loaded.resolved_workspace.workspace_name == "lab"
    assert config.file_path == (workspace / "state" / "logs" / "custom.log").resolve()
    assert root.level == original_level
    assert list(root.handlers) == original_handlers


def test_load_workspace_logging_config_preserves_stable_symlink_path_when_log_exists(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "lab"
    WorkspaceService().init_workspace(workspace)
    symlink = workspace / "runtime" / "logs" / "arbor-ddns.log"
    daily_file = workspace / "runtime" / "logs" / "arbor-ddns-2026-04-01.log"
    daily_file.parent.mkdir(parents=True, exist_ok=True)
    daily_file.write_text("existing\n", encoding="utf-8")
    symlink.symlink_to(daily_file)

    _loaded, config = load_workspace_logging_config(workspace)

    assert config.file_path == symlink


def test_apply_logging_config_uses_supplied_runtime_config(tmp_path: Path) -> None:
    config = ResolvedLoggingConfig(
        level=logging.INFO,
        format="%(message)s",
        file_path=tmp_path / "arbor-ddns.log",
        retention_days=7,
        stream="none",
    )

    with _restore_root_logger():
        apply_logging_config(config, close_existing=True)
        logging.getLogger("arbor_ddns.test").info("applied from runtime config")

    symlink = tmp_path / "arbor-ddns.log"
    assert symlink.is_symlink()
    assert "applied from runtime config" in symlink.resolve().read_text(encoding="utf-8")


def test_apply_logging_config_reapply_keeps_stable_symlink_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixed_now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

    class FixedNowDailySymlinkFileHandler(DailySymlinkFileHandler):
        def __init__(
            self,
            symlink_path,
            *,
            retention_days=7,
            encoding="utf-8",
            now_func=None,
        ) -> None:
            _ = now_func
            super().__init__(
                symlink_path,
                retention_days=retention_days,
                encoding=encoding,
                now_func=lambda: fixed_now,
            )

    monkeypatch.setattr(
        logging_runtime,
        "DailySymlinkFileHandler",
        FixedNowDailySymlinkFileHandler,
    )
    config = ResolvedLoggingConfig(
        level=logging.INFO,
        format="%(message)s",
        file_path=tmp_path / "arbor-ddns.log",
        retention_days=7,
        stream="none",
    )

    with _restore_root_logger():
        apply_logging_config(config, close_existing=True)
        logging.getLogger("arbor_ddns.test").info("first write")
        apply_logging_config(config, close_existing=True)
        logging.getLogger("arbor_ddns.test").info("second write")

    symlink = tmp_path / "arbor-ddns.log"
    dated_file = tmp_path / "arbor-ddns-2026-04-01.log"
    duplicate_file = tmp_path / "arbor-ddns-2026-04-01-2026-04-01.log"

    assert symlink.is_symlink()
    assert symlink == tmp_path / "arbor-ddns.log"
    assert symlink.resolve() == dated_file.resolve()
    assert dated_file.exists()
    assert duplicate_file.exists() is False
    assert "first write" in dated_file.read_text(encoding="utf-8")
    assert "second write" in dated_file.read_text(encoding="utf-8")


def test_workspace_logging_context_uses_workspace_file_without_default_stderr_output(
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "lab"
    WorkspaceService().init_workspace(workspace)

    with _restore_root_logger():
        configure_default_logging()
        with workspace_logging_context(
            workspace,
            command_name="plan",
        ):
            logging.getLogger("arbor_ddns.test").info("workspace logging active")
        logging.getLogger("arbor_ddns.test").warning("restored stderr logging")

    captured = capsys.readouterr()
    assert "workspace logging active" not in captured.err
    assert "restored stderr logging" in captured.err
    symlink = workspace / "runtime" / "logs" / "arbor-ddns.log"
    assert symlink.is_symlink()
    log_payload = symlink.resolve().read_text(encoding="utf-8")
    assert "workspace logging active" in log_payload
    assert "workspace=lab" in log_payload
    assert "command=plan" in log_payload


def test_workspace_logging_context_fails_fast_for_missing_workspace_config(tmp_path: Path) -> None:
    with _restore_root_logger():
        configure_default_logging()
        with pytest.raises(WorkspaceLoadError, match="workspace file not found"):
            with workspace_logging_context(
                tmp_path,
                command_name="plan",
            ):
                pass


def test_absolute_path_without_symlink_resolution_uses_base_dir_for_relative_paths(
    tmp_path: Path,
) -> None:
    path = absolute_path_without_symlink_resolution(
        "runtime/logs/arbor-ddns.log",
        base_dir=tmp_path / "lab",
    )

    assert path == tmp_path / "lab" / "runtime" / "logs" / "arbor-ddns.log"


def test_absolute_path_without_symlink_resolution_preserves_existing_symlink_name(
    tmp_path: Path,
) -> None:
    symlink = tmp_path / "arbor-ddns.log"
    dated_file = tmp_path / "arbor-ddns-2026-04-01.log"
    dated_file.write_text("existing\n", encoding="utf-8")
    symlink.symlink_to(dated_file)

    path = absolute_path_without_symlink_resolution(symlink)

    assert path == symlink
    assert path != symlink.resolve()
