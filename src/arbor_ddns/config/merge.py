"""Canonical deep-merge helper for runtime config and scaffold mappings."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge mappings and otherwise replace with the override."""

    if isinstance(base, Mapping) and isinstance(override, Mapping):
        merged: dict[str, Any] = {key: deepcopy(value) for key, value in base.items()}
        for key, value in override.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    return deepcopy(override)
