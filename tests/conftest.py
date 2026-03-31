from __future__ import annotations

from pathlib import Path

import pytest

from arbor_ddns.workspace.service import WorkspaceService


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
