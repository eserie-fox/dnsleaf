"""Raw strategy declarations and the single field-by-field effective resolver."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from dnsleaf.config.merge import deep_merge
from dnsleaf.config.resources import read_json_mapping
from dnsleaf.models import IPAddressFamily

SelectionPolicy = Literal["default", "require-dhcpv6"]
EvidenceSource = Literal["none", "windows-powershell"]
StrategyOrigin = Literal["entry", "cli", "source_default", "built_in"]


class StrategyDefaults(BaseModel):
    """Package-supplied built-in strategy values."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    selection_policy: SelectionPolicy
    evidence: EvidenceSource

    @classmethod
    def from_defaults(cls) -> StrategyDefaults:
        return cls.from_mapping({})

    @classmethod
    def from_file(cls, path: str | Path) -> StrategyDefaults:
        return cls.from_mapping(read_json_mapping(path))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> StrategyDefaults:
        return cls.model_validate(
            deep_merge(read_json_mapping("pkg://dnsleaf/config_defaults/strategy.json"), data)
        )


class StrategyOverrides(BaseModel):
    """Nullable consumer overrides; null is inheritance, never a reset string."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    selection_policy: SelectionPolicy | None = None
    evidence: EvidenceSource | None = None


class SourceDefault(BaseModel):
    """One exact VM-ID group; partial fields are resolved only for consumers."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    source_kind: Literal["vm"]
    source_ids: list[Annotated[StrictInt, Field(gt=0)]] = Field(min_length=1)
    selection_policy: SelectionPolicy | None = None
    evidence: EvidenceSource | None = None

    @model_validator(mode="after")
    def _validate_group(self) -> Self:
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must not repeat within a source-default group")
        if self.selection_policy is None and self.evidence is None:
            raise ValueError("source-default group requires at least one non-null strategy setting")
        return self


class ResolvedStrategy(BaseModel):
    """Effective strategy and provenance; shared by operation and presentation."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    selection_policy: SelectionPolicy
    evidence: EvidenceSource
    selection_policy_origin: StrategyOrigin
    evidence_origin: StrategyOrigin

    @property
    def requires_evidence(self) -> bool:
        return self.selection_policy == "require-dhcpv6"


def validate_strategy_source(
    *,
    source_kind: str,
    families: tuple[IPAddressFamily, ...],
    selection_policy: SelectionPolicy | None,
    evidence: EvidenceSource | None,
) -> None:
    """Intrinsic rules, independent of inheritance or completeness."""
    if source_kind == "static" and (selection_policy is not None or evidence is not None):
        raise ValueError("static entries must not define non-null selection_policy or evidence")
    if evidence == "windows-powershell" and source_kind != "vm":
        raise ValueError("evidence=windows-powershell requires source_kind=vm")
    if selection_policy == "require-dhcpv6" and IPAddressFamily.IPV6 not in families:
        raise ValueError("require-dhcpv6 requires family=ipv6 or both")


def resolve_strategy(
    *,
    source_kind: str,
    source_id: int | None,
    families: tuple[IPAddressFamily, ...],
    selection_policy: SelectionPolicy | None = None,
    evidence: EvidenceSource | None = None,
    source_defaults: Sequence[SourceDefault] = (),
    override_origin: Literal["entry", "cli"],
    builtins: StrategyDefaults,
) -> ResolvedStrategy:
    """Resolve each field independently, then validate the effective combination."""
    group = next(
        (g for g in source_defaults if source_kind == g.source_kind and source_id in g.source_ids),
        None,
    )
    group_policy = group.selection_policy if group is not None else None
    group_evidence = group.evidence if group is not None else None
    policy = selection_policy if selection_policy is not None else group_policy
    permitted = evidence if evidence is not None else group_evidence
    resolved = ResolvedStrategy(
        selection_policy=policy if policy is not None else builtins.selection_policy,
        evidence=permitted if permitted is not None else builtins.evidence,
        selection_policy_origin=(
            override_origin
            if selection_policy is not None
            else "source_default"
            if group_policy is not None
            else "built_in"
        ),
        evidence_origin=(
            override_origin
            if evidence is not None
            else "source_default"
            if group_evidence is not None
            else "built_in"
        ),
    )
    validate_strategy_source(
        source_kind=source_kind,
        families=families,
        selection_policy=resolved.selection_policy,
        evidence=resolved.evidence,
    )
    if resolved.requires_evidence and resolved.evidence == "none":
        raise ValueError(
            "require-dhcpv6 requires evidence=windows-powershell; effective evidence is none"
        )
    return resolved
