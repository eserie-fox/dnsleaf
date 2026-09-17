from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import pytest

from dnsleaf.workspace.service import WorkspaceService


def scaffold_workspace(tmp_path: Path, name: str = "lab") -> Path:
    service = WorkspaceService()
    workspace = tmp_path / name
    service.init_workspace(workspace)
    (workspace / "secrets" / "cloudflare_api_token.txt").write_text(
        "secret-token\n",
        encoding="utf-8",
    )
    return workspace


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    return scaffold_workspace(tmp_path)


@pytest.fixture(autouse=True)
def block_host_commands_and_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must inject process runners and HTTP transports."""

    def denied(*args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("tests must use fake commands and network transports")

    monkeypatch.setattr("subprocess.run", denied)
    monkeypatch.setattr("socket.create_connection", denied)


@pytest.fixture(autouse=True)
def isolate_workspace_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """No unmatched command test may inspect the developer's ancestors/home."""

    monkeypatch.delenv("DNSLEAF_WORKSPACE", raising=False)
    monkeypatch.setattr("dnsleaf.workspace.locator.search_bases", lambda cwd, home: [cwd])
