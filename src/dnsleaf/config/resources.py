"""Minimal package resource loading helpers."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any, TextIO

import yaml

_PKG_SCHEME = "pkg://"


def read_text(spec: str | Path, *, encoding: str = "utf-8") -> str:
    """Read text from a filesystem path or ``pkg://`` resource spec."""

    if isinstance(spec, Path):
        return spec.read_text(encoding=encoding)

    text = str(spec)
    if not text.startswith(_PKG_SCHEME):
        return Path(text).expanduser().read_text(encoding=encoding)

    payload = text[len(_PKG_SCHEME) :]
    parts = [part for part in payload.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"invalid package resource spec: {spec}")

    package = parts[0]
    resource_parts = parts[1:]
    return resources.files(package).joinpath(*resource_parts).read_text(encoding=encoding)


def read_json(spec: str | Path) -> Any:
    """Read JSON from a filesystem path or ``pkg://`` resource spec."""

    return json.loads(read_text(spec))


def read_json_mapping(spec: str | Path) -> dict[str, Any]:
    """Read and validate a JSON object resource."""

    payload = read_json(spec)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON resource root must be an object: {spec}")
    return payload


def read_yaml_mapping(path: str | Path) -> dict[str, Any]:
    """Read one YAML override without including source values in parse errors."""

    try:
        with open_regular_text_file(Path(path)) as handle:
            payload = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ValueError(f"invalid YAML in {path}{location}") from None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping content in {path}")
    return payload


__all__ = ["read_json", "read_json_mapping", "read_text"]


def check_regular_readable_file(path: Path) -> None:
    """Check layout/readability without reading or parsing configuration."""

    with open_regular_text_file(path):
        pass


@contextmanager
def open_regular_text_file(path: Path) -> Iterator[TextIO]:
    """Reject special files, including a replacement between stat and open."""

    if not stat.S_ISREG(path.stat().st_mode):
        raise OSError(f"source path is not a regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError(f"source path is not a regular file: {path}")
        yield handle
