"""Inventory models and loading helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from arbor_ddns.models import InventoryEntry


def _normalize_inventory_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    if "entries" in data:
        return dict(data)
    raise KeyError("inventory mapping must contain an 'entries' key")


class Inventory(BaseModel):
    """Inventory container."""

    model_config = ConfigDict(extra="forbid")

    entries: list[InventoryEntry] = Field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Inventory:
        """Load inventory from a JSON-like mapping."""

        return cls.model_validate(_normalize_inventory_mapping(data))

    @classmethod
    def from_file(cls, path: str | Path) -> Inventory:
        """Load inventory from a JSON file."""

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return cls.model_validate({"entries": payload})
        if isinstance(payload, dict):
            return cls.from_mapping(payload)
        raise TypeError("inventory JSON must be an object or list")

    def enabled_entries(self) -> list[InventoryEntry]:
        """Return enabled targets only."""

        return [entry for entry in self.entries if entry.enabled]
