"""Shared dnsleaf logging configuration models and helpers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LoggingStream = Literal["stdout", "stderr", "none"]

_LOG_LEVELS: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def normalize_log_level_name(value: str) -> str:
    """Normalize and validate a string log level name."""

    stripped = value.strip().upper()
    if stripped not in _LOG_LEVELS:
        allowed = ", ".join(sorted(_LOG_LEVELS))
        raise ValueError(f"invalid logging level {value!r}; expected one of: {allowed}")
    return stripped


def resolved_log_level(value: str) -> int:
    """Return the stdlib logging level integer for one normalized level name."""

    return _LOG_LEVELS[normalize_log_level_name(value)]


def absolute_path_without_symlink_resolution(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> Path:
    """Return one absolute path without dereferencing the final symlink target."""

    raw_path = Path(path).expanduser()
    if not raw_path.is_absolute():
        base_path = Path.cwd() if base_dir is None else Path(base_dir).expanduser()
        raw_path = base_path / raw_path
    return Path(os.path.abspath(raw_path))


class ResolvedDnsleafLoggingConfig(BaseModel):
    """Runtime-resolved dnsleaf logging config."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    level: str
    format: str
    file_path: str | None = None
    retention_days: int = Field(ge=1)
    stream: LoggingStream

    def resolved_level(self) -> int:
        """Return the stdlib logging level integer."""

        return resolved_log_level(self.level)

    def resolved_file_path(self) -> Path | None:
        """Return the resolved log path, if file logging is enabled."""

        if self.file_path is None:
            return None
        return Path(self.file_path)


class DnsleafLoggingConfig(BaseModel):
    """Shared dnsleaf logging schema."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    level: str
    format: str
    file_path: str | None
    retention_days: int = Field(ge=1)
    stream: LoggingStream

    @field_validator("level")
    @classmethod
    def _normalize_level(cls, value: str) -> str:
        return normalize_log_level_name(value)

    @field_validator("format")
    @classmethod
    def _validate_format(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("dnsleaf_logging.format must not be blank")
        return stripped

    @field_validator("file_path")
    @classmethod
    def _strip_optional_file_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def resolved_log_path(self, base_dir: str | Path | None = None) -> Path | None:
        """Resolve the configured log path."""

        if self.file_path is None:
            return None
        return absolute_path_without_symlink_resolution(self.file_path, base_dir=base_dir)

    def resolved_level(self) -> int:
        """Return the stdlib logging level integer."""

        return resolved_log_level(self.level)

    def resolve(
        self,
        base_dir: str | Path | None = None,
    ) -> ResolvedDnsleafLoggingConfig:
        """Resolve runtime-only logging values."""

        resolved_path = self.resolved_log_path(base_dir)
        return ResolvedDnsleafLoggingConfig(
            level=self.level,
            format=self.format,
            file_path=str(resolved_path) if resolved_path is not None else None,
            retention_days=self.retention_days,
            stream=self.stream,
        )
