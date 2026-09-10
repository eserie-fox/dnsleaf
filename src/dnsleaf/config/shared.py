"""Shared config sub-models used across workspace and outside-workspace config."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class DiscoveryCommandPaths(BaseModel):
    """Shared discovery command locations."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    pct_bin: str
    qm_bin: str
    shell_bin: str

    @field_validator("pct_bin", "qm_bin", "shell_bin")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("command paths must not be blank")
        return stripped
