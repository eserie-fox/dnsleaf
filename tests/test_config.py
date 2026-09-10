from __future__ import annotations

from typing import Any

from dnsleaf.config.merge import deep_merge
from dnsleaf.config.outside_workspace import OutsideWorkspaceConfig


def test_from_defaults_loads_packaged_outside_workspace_config() -> None:
    config = OutsideWorkspaceConfig.from_defaults()

    assert config.paths.pct_bin == "pct"
    assert config.paths.qm_bin == "qm"
    assert config.dnsleaf_logging.level == "INFO"
    assert config.dnsleaf_logging.stream == "stderr"
    assert config.dnsleaf_logging.file_path is None
    assert "config_version" not in config.model_dump()


def test_from_file_none_falls_back_to_defaults() -> None:
    assert OutsideWorkspaceConfig.from_file(None).model_dump() == (
        OutsideWorkspaceConfig.from_defaults().model_dump()
    )


def test_from_mapping_deep_merges_outside_workspace_config() -> None:
    config = OutsideWorkspaceConfig.from_mapping(
        {
            "paths": {
                "pct_bin": "/usr/sbin/pct",
            },
            "dnsleaf_logging": {
                "level": "debug",
            },
        }
    )

    assert config.paths.pct_bin == "/usr/sbin/pct"
    assert config.paths.qm_bin == "qm"
    assert config.dnsleaf_logging.level == "DEBUG"
    assert config.dnsleaf_logging.stream == "stderr"


def test_deep_merge_replaces_lists_instead_of_concatenating() -> None:
    merged = deep_merge(
        {"a": {"items": [1, 2], "value": "base"}},
        {"a": {"items": [3], "other": True}},
    )

    assert merged == {"a": {"items": [3], "value": "base", "other": True}}


def test_workspace_constructors_merge_before_validation_and_resolve_explicitly(tmp_path) -> None:
    from dnsleaf.workspace.models import WorkspaceConfig

    override = {
        "workspace_name": "demo",
        "api_token_file": "credentials/token.txt",
        "dnsleaf_logging": {"level": "DEBUG"},
    }
    config = WorkspaceConfig.from_mapping(override)
    file = tmp_path / "workspace.yaml"
    file.write_text(
        "workspace_name: demo\napi_token_file: credentials/token.txt\n"
        "dnsleaf_logging:\n  level: DEBUG\n"
    )
    assert WorkspaceConfig.from_file(file) == config
    assert config.api_token_file == "credentials/token.txt"
    assert config.paths == WorkspaceConfig.from_defaults().paths
    assert config.resolved_api_token_file(tmp_path) == tmp_path / "credentials/token.txt"
    assert config.dnsleaf_logging.stream == "none"


def test_unknown_fields_and_wrong_scalar_types_are_rejected() -> None:
    import pytest

    from dnsleaf.workspace.models import WorkspaceConfig

    cases: list[dict[str, Any]] = [
        {"arbor_ddns_logging": {}},
        {"dnsleaf_logging": {"unknown": "TEST_ONLY_SECRET"}},
        {"apply": {"prune_managed_records": "false"}},
        {"config_version": "4"},
        {"default_proxied": "true"},
        {"default_ttl": "120"},
    ]
    for data in cases:
        with pytest.raises(ValueError) as error:
            WorkspaceConfig.from_mapping(data)
        assert "TEST_ONLY_SECRET" not in str(error.value)


def test_entries_constructors_and_replacement(tmp_path) -> None:
    from dnsleaf.workspace.models import EntriesFile

    defaults = EntriesFile.from_defaults()
    file = tmp_path / "entries.yaml"
    file.write_text("entries: []\n")
    assert EntriesFile.from_file(file) == defaults
    assert EntriesFile.from_mapping({"entries": []}) == defaults


def test_yaml_nonmapping_values_and_errors_do_not_leak_input(tmp_path) -> None:
    import pytest

    from dnsleaf.workspace.models import WorkspaceConfig

    file = tmp_path / "workspace.yaml"
    for text in ["false", "[]", "123", "[TEST_ONLY_SECRET: {\n"]:
        file.write_text(text)
        with pytest.raises(ValueError) as error:
            WorkspaceConfig.from_file(file)
        assert "TEST_ONLY_SECRET" not in str(error.value)
