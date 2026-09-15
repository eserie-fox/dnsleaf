from __future__ import annotations

from pathlib import Path

from dnsleaf.config.resources import read_json_mapping, read_text
from dnsleaf.config.scaffold import (
    load_entries_defaults,
    load_scaffold_layout,
    load_scaffold_secrets_readme,
    load_workspace_defaults,
)


def test_config_default_resources_are_readable_via_package_loaders() -> None:
    outside_workspace_defaults = read_json_mapping(
        "pkg://dnsleaf/config_defaults/outside_workspace.json"
    )
    workspace_defaults = load_workspace_defaults()
    entries_defaults = load_entries_defaults()
    layout = load_scaffold_layout()
    secrets_readme = load_scaffold_secrets_readme()

    assert "config_version" not in outside_workspace_defaults
    assert outside_workspace_defaults["dnsleaf_logging"]["stream"] == "stderr"
    assert outside_workspace_defaults["paths"]["pct_bin"] == "pct"
    assert workspace_defaults["config_version"] == 4
    assert workspace_defaults["default_ttl"] == "auto"
    assert workspace_defaults["default_proxied"] is None
    assert workspace_defaults["dnsleaf_logging"]["file_path"] == "runtime/logs/dnsleaf.log"
    assert workspace_defaults["dnsleaf_logging"]["stream"] == "none"
    assert workspace_defaults["paths"]["systemctl_bin"] == "systemctl"
    assert entries_defaults == {"config_version": 2, "entries": []}
    assert "runtime/logs" in layout.directories
    assert "Place secret material" in secrets_readme


def test_read_text_supports_package_resource_and_filesystem_paths(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("hello\n", encoding="utf-8")

    assert read_text(sample) == "hello\n"
    assert "Do not commit real secrets" in read_text("pkg://dnsleaf/templates/secrets_readme.txt")


def test_pyproject_includes_runtime_resources() -> None:
    import tomllib

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["setuptools"]["package-data"]["dnsleaf"] == [
        "config_defaults/*.json",
        "templates/*.json",
        "templates/*.txt",
    ]
