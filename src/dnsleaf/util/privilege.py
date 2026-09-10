"""Explicit privilege checks; commands never elevate themselves."""

from __future__ import annotations

import os
import shlex
import sys


def permission_hint() -> str:
    """Describe an explicit invocation that preserves the installing environment."""

    entry = shlex.join([os.path.abspath(sys.executable), "-m", "dnsleaf"])
    return f"Run as root or use explicit sudo with this absolute entry: sudo {entry} <command>"


def require_root(operation: str) -> None:
    """Check only operations that manage system-level units."""

    if os.geteuid() != 0:
        raise PermissionError(f"{operation} requires root privileges for system-level systemd")
