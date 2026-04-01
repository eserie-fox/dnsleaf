from __future__ import annotations

from pathlib import Path

from arbor_ddns.config import (
    load_entries_scaffold_defaults,
    load_scaffold_layout,
    load_scaffold_secrets_readme,
    load_workspace_scaffold_defaults,
    read_json_mapping,
    read_text,
)


def test_config_default_resources_are_readable_via_package_loaders() -> None:
    outside_workspace_defaults = read_json_mapping(
        "pkg://arbor_ddns/config_defaults/outside_workspace.json"
    )
    workspace_defaults = load_workspace_scaffold_defaults()
    entries_defaults = load_entries_scaffold_defaults()
    layout = load_scaffold_layout()
    secrets_readme = load_scaffold_secrets_readme()

    assert "config_version" not in outside_workspace_defaults
    assert outside_workspace_defaults["arbor_ddns_logging"]["stream"] == "stderr"
    assert outside_workspace_defaults["paths"]["pct_bin"] == "pct"
    assert workspace_defaults["config_version"] == 3
    assert workspace_defaults["arbor_ddns_logging"]["file_path"] == "runtime/logs/arbor-ddns.log"
    assert workspace_defaults["arbor_ddns_logging"]["stream"] == "none"
    assert workspace_defaults["paths"]["systemctl_bin"] == "systemctl"
    assert entries_defaults == {"config_version": 2, "entries": []}
    assert "runtime/logs" in layout.directories
    assert "Place secret material" in secrets_readme


def test_read_text_supports_package_resource_and_filesystem_paths(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("hello\n", encoding="utf-8")

    assert read_text(sample) == "hello\n"
    assert "Do not commit real secrets" in read_text(
        "pkg://arbor_ddns/config_defaults/scaffold_secrets_readme.txt"
    )


def test_pyproject_sdist_includes_recursive_config_default_resources() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "/src/arbor_ddns/config_defaults/**/*" in pyproject
