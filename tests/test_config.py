from __future__ import annotations

from arbor_ddns.config import AppConfig
from arbor_ddns.util.json_merge import deep_merge


def test_from_defaults_loads_packaged_defaults() -> None:
    config = AppConfig.from_defaults()

    assert config.discovery.pct_bin == "pct"
    assert config.dns.default_ttl == 300
    assert len(config.inventory.entries) == 1
    assert config.inventory.entries[0].enabled is False


def test_from_file_none_falls_back_to_defaults() -> None:
    assert AppConfig.from_file(None).model_dump() == AppConfig.from_defaults().model_dump()


def test_from_mapping_deep_merges_and_replaces_lists() -> None:
    config = AppConfig.from_mapping(
        {
            "dns": {"default_ttl": 60},
            "inventory": {
                "entries": [
                    {
                        "kind": "vm",
                        "id": 200,
                        "fqdn": "vm.example.com",
                        "provider": "cloudflare",
                        "selection_policy": "default",
                        "enabled": True,
                    }
                ]
            },
        }
    )

    assert config.dns.default_ttl == 60
    assert len(config.inventory.entries) == 1
    assert config.inventory.entries[0].kind.value == "vm"


def test_deep_merge_replaces_lists_instead_of_concatenating() -> None:
    merged = deep_merge(
        {"a": {"items": [1, 2], "value": "base"}},
        {"a": {"items": [3], "other": True}},
    )

    assert merged == {"a": {"items": [3], "value": "base", "other": True}}
