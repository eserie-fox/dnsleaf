from __future__ import annotations

from arbor_ddns.config import OutsideWorkspaceConfig, deep_merge


def test_from_defaults_loads_packaged_outside_workspace_config() -> None:
    config = OutsideWorkspaceConfig.from_defaults()

    assert config.paths.pct_bin == "pct"
    assert config.paths.qm_bin == "qm"
    assert config.arbor_ddns_logging.level == "INFO"
    assert config.arbor_ddns_logging.stream == "stderr"
    assert config.arbor_ddns_logging.file_path is None
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
            "arbor_ddns_logging": {
                "level": "debug",
            },
        }
    )

    assert config.paths.pct_bin == "/usr/sbin/pct"
    assert config.paths.qm_bin == "qm"
    assert config.arbor_ddns_logging.level == "DEBUG"
    assert config.arbor_ddns_logging.stream == "stderr"


def test_deep_merge_replaces_lists_instead_of_concatenating() -> None:
    merged = deep_merge(
        {"a": {"items": [1, 2], "value": "base"}},
        {"a": {"items": [3], "other": True}},
    )

    assert merged == {"a": {"items": [3], "value": "base", "other": True}}
