from __future__ import annotations

import json

from arbor_ddns.inventory import Inventory


def test_inventory_from_mapping_and_enabled_entries() -> None:
    inventory = Inventory.from_mapping(
        {
            "entries": [
                {
                    "kind": "lxc",
                    "id": 101,
                    "fqdn": "one.example.com",
                    "provider": "cloudflare",
                    "selection_policy": "default",
                    "enabled": True,
                },
                {
                    "kind": "vm",
                    "id": 201,
                    "fqdn": "two.example.com",
                    "provider": "alidns",
                    "selection_policy": "default",
                    "enabled": False,
                },
            ]
        }
    )

    enabled = inventory.enabled_entries()

    assert len(inventory.entries) == 2
    assert len(enabled) == 1
    assert enabled[0].fqdn == "one.example.com"


def test_inventory_from_file_supports_top_level_list(tmp_path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(
        json.dumps(
            [
                {
                    "kind": "lxc",
                    "id": 101,
                    "fqdn": "one.example.com",
                    "provider": "cloudflare",
                    "selection_policy": "default",
                    "enabled": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    inventory = Inventory.from_file(path)

    assert len(inventory.entries) == 1
    assert inventory.entries[0].id == 101

