"""Resolve every declared dynamic consumer at the workspace validation boundary."""

from dnsleaf.config.strategy import ResolvedStrategy, StrategyDefaults, resolve_strategy
from dnsleaf.models import EntrySourceKind
from dnsleaf.workspace.models import EntriesFile, WorkspaceConfig


def resolve_entry_strategies(
    workspace: WorkspaceConfig, entries: EntriesFile
) -> dict[str, ResolvedStrategy]:
    builtins = StrategyDefaults.from_defaults()
    strategies = {}
    for entry in entries.entries:
        if entry.source_kind is EntrySourceKind.STATIC:
            continue
        try:
            strategies[entry.name] = resolve_strategy(
                source_kind=entry.source_kind.value,
                source_id=entry.source_id,
                families=entry.concrete_families(),
                selection_policy=entry.selection_policy,
                evidence=entry.evidence,
                source_defaults=workspace.source_defaults,
                override_origin="entry",
                builtins=builtins,
            )
        except ValueError as exc:
            raise ValueError(f"entry {entry.name!r} effective strategy: {exc}") from exc
    return strategies
