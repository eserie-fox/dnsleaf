"""Deterministic, one-level workspace search, separate from configuration loading."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from dnsleaf.config.resources import check_regular_readable_file

WORKSPACE_ENV = "DNSLEAF_WORKSPACE"
REQUIRED_FILES = ("workspace.yaml", "entries.yaml")


class WorkspaceNotFoundError(RuntimeError):
    """No complete workspace exists in the inspected locations."""

    def __init__(self, checked: list[Path], incomplete: list[str]) -> None:
        self.incomplete = incomplete
        super().__init__(
            "Unable to locate a complete dnsleaf workspace. Required files: "
            + ", ".join(REQUIRED_FILES)
            + ".\nSearch order: cwd, nearest-to-farthest ancestors (including root), then home; "
            "at each base, sorted immediate child directories before the base itself.\n"
            "Checked locations:\n"
            + "\n".join(f"- {path}" for path in checked)
            + ("\nIncomplete candidates:\n" + "\n".join(incomplete) if incomplete else "")
            + "\nPass --workspace, set DNSLEAF_WORKSPACE, or use 'dnsleaf init DIRECTORY'."
        )


def search_bases(cwd: Path, home: Path) -> list[Path]:
    """Return normalized, deduplicated bases in precedence order."""

    current = cwd.expanduser().resolve()
    return list(dict.fromkeys(p.expanduser().resolve() for p in [current, *current.parents, home]))


def missing_source_files(root: Path) -> list[str]:
    """Inspect layout only; propagate every failure except confirmed absence."""

    missing: list[str] = []
    for name in REQUIRED_FILES:
        path = root / name
        try:
            check_regular_readable_file(path)
        except FileNotFoundError:
            # A dangling symlink exists but cannot supply a source file.
            try:
                path.lstat()
            except FileNotFoundError:
                missing.append(name)
            else:
                raise OSError(f"source file is a dangling symlink or disappeared: {path}") from None
    return missing


def _warn(message: str) -> None:
    print(f"warning={message}", file=sys.stderr)


def locate_workspace(
    workspace: str | Path | None = None,
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    warn: Callable[[str], None] = _warn,
) -> Path:
    """Select once. Explicit and environment paths are always authoritative."""

    environment = os.environ if env is None else env
    selected = workspace if workspace is not None else environment.get(WORKSPACE_ENV)
    current = Path.cwd() if cwd is None else cwd
    if selected is not None and (workspace is not None or str(selected)):
        path = Path(selected).expanduser()
        root = (current / path).resolve()
        if not stat.S_ISDIR(root.stat().st_mode):
            raise OSError(f"workspace root is not a directory: {root}")
        missing = missing_source_files(root)
        if missing:
            raise RuntimeError(f"selected workspace {root}: missing {', '.join(missing)}")
        return root

    checked: list[Path] = []
    seen: set[Path] = set()
    incomplete: list[str] = []

    def inspect(candidate: Path) -> Path | None:
        root = candidate.resolve()
        if root in seen:
            return None
        seen.add(root)
        checked.append(root)
        missing = missing_source_files(root)
        if not missing:
            return root
        if len(missing) < len(REQUIRED_FILES):
            message = (
                f"possibly incomplete workspace {root}: missing {', '.join(missing)}; "
                "another project may use the same filename"
            )
            incomplete.append(message)
            warn(message)
        return None

    for base in search_bases(current, Path.home() if home is None else home):
        for child in sorted(base.iterdir(), key=lambda p: p.name):
            try:
                is_directory = stat.S_ISDIR(child.stat().st_mode)
            except FileNotFoundError:
                continue  # An unselected directory entry disappeared or is a dangling link.
            if is_directory:
                found = inspect(child)
                if found is not None:
                    return found
        found = inspect(base)
        if found is not None:
            return found
    raise WorkspaceNotFoundError(checked, incomplete)
