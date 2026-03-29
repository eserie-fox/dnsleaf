"""Deterministic deep-merge helpers for raw config mappings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def deep_merge(base: Any, override: Any) -> Any:
    """Merge two JSON-like values with a strict mapping-only recursive rule."""

    if isinstance(base, dict) and isinstance(override, dict):
        merged: dict[str, Any] = {key: deepcopy(value) for key, value in base.items()}
        for key, value in override.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    return deepcopy(override)

