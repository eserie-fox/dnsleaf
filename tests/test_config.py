from __future__ import annotations

from arbor_ddns.config import AppConfig
from arbor_ddns.util.json_merge import deep_merge


def test_from_defaults_loads_packaged_defaults() -> None:
    config = AppConfig.from_defaults()

    assert config.discovery.pct_bin == "pct"
    assert config.systemd.systemctl_bin == "systemctl"
    assert config.workspace_scaffold.api_token_file == "secrets/cloudflare_api_token.txt"
    assert config.workspace_scaffold.systemd.on_unit_active_sec == "10min"


def test_from_file_none_falls_back_to_defaults() -> None:
    assert AppConfig.from_file(None).model_dump() == AppConfig.from_defaults().model_dump()


def test_from_mapping_deep_merges_runtime_config() -> None:
    config = AppConfig.from_mapping(
        {
            "systemd": {
                "unit_dir": "/tmp/arbor-ddns-tests",
            },
            "workspace_scaffold": {
                "zone_name": "lab.example.com",
                "systemd": {
                    "on_unit_active_sec": "30min",
                },
            },
        }
    )

    assert config.systemd.unit_dir == "/tmp/arbor-ddns-tests"
    assert config.workspace_scaffold.zone_name == "lab.example.com"
    assert config.workspace_scaffold.systemd.on_unit_active_sec == "30min"
    assert config.workspace_scaffold.systemd.on_boot_sec == "2min"


def test_deep_merge_replaces_lists_instead_of_concatenating() -> None:
    merged = deep_merge(
        {"a": {"items": [1, 2], "value": "base"}},
        {"a": {"items": [3], "other": True}},
    )

    assert merged == {"a": {"items": [3], "value": "base", "other": True}}
