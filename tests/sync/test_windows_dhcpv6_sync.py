"""End-to-end orchestration with synthetic commands and an in-memory DNS provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from dnsleaf.discovery.models import AddressCandidate
from dnsleaf.discovery.pve_qga import PVEQGADiscoveryBackend
from dnsleaf.discovery.windows import WindowsMetadataProbe
from dnsleaf.dns.models import DNSRecord
from dnsleaf.models import IPAddressFamily
from dnsleaf.sync.runner import SyncRunner
from dnsleaf.workspace.models import EntriesFile, ManagedRecordFile, ManagedRecordSnapshot
from dnsleaf.workspace.storage import WorkspaceStorage
from tests.fakes import FakeDNSProvider
from tests.windows_fixtures import DHCP, LINK, SyntheticWindowsCommands


def entry(name="strict", policy="windows-dhcpv6", family="ipv6", vmid=201):
    return dict(
        name=name,
        source_kind="vm",
        source_id=vmid,
        family=family,
        fqdn=f"{name}.example.com",
        enabled=True,
        selection_policy=policy,
        proxied=False,
    )


def make_runner(commands, provider):
    return SyncRunner(
        discovery_backends={"vm": PVEQGADiscoveryBackend(runner=commands)},
        windows_probe=WindowsMetadataProbe(runner=commands),
        provider_factory=lambda _: provider,
    )


def load(workspace_dir, entries):
    loaded = WorkspaceStorage().load(workspace_dir)
    loaded.entries_file = EntriesFile.from_mapping({"entries": entries})
    return loaded


def run(runner, loaded, *, apply=False, state=None):
    return runner.run(
        loaded,
        apply=apply,
        prune_managed=True,
        managed_state=state if state is not None else ManagedRecordFile(),
    )


def add_ipv4(commands, value="8.8.8.8"):
    commands.raw.candidates.append(
        AddressCandidate(
            family=IPAddressFamily.IPV4,
            interface="Ethernet 以太网",
            address=value,
            prefix_length=24,
            source="pve_qga",
        )
    )


@pytest.mark.parametrize("strict_first", [False, True])
def test_mixed_policies_share_raw_and_metadata_and_refresh_next_run(workspace_dir, strict_first):
    commands = SyntheticWindowsCommands()
    provider = FakeDNSProvider()
    entries = [
        entry("default", "default"),
        entry(),
        entry("service", family="both"),
        entry("other", vmid=202),
    ]
    if strict_first:
        entries.reverse()
    loaded = load(workspace_dir, entries)
    runner = make_runner(commands, provider)
    first = run(runner, loaded)
    by_name = {o.entry_name: o for o in first.record_outcomes if o.family is IPAddressFamily.IPV6}
    assert by_name["default"].selection_status == "ambiguous"
    assert by_name["default"].selection and by_name["default"].selection.supplementary is None
    assert by_name["strict"].selected_value == by_name["service"].selected_value == DHCP
    assert by_name["strict"].discovery is by_name["default"].discovery
    assert by_name["strict"].discovery is not by_name["other"].discovery
    assert len([c for c in commands.calls if c[1] == "agent"]) == 2
    assert len([c for c in commands.calls if c[1] == "guest"]) == 2
    snapshot = by_name["strict"].discovery.model_dump()
    commands.records[0].update(PrefixOrigin="RouterAdvertisement", SuffixOrigin="Random")
    commands.records[2].update(PrefixOrigin="Dhcp", SuffixOrigin="Dhcp")
    second = run(runner, loaded)
    assert len(commands.calls) == 8
    assert (
        next(o for o in second.record_outcomes if o.entry_name == "strict").selected_value == LINK
    )
    assert by_name["strict"].discovery.model_dump() == snapshot
    assert provider.applied_actions == []


def test_default_vm_performs_only_existing_raw_command(workspace_dir):
    commands = SyntheticWindowsCommands()
    loaded = load(workspace_dir, [entry(policy="default")])
    report = run(make_runner(commands, FakeDNSProvider()), loaded)
    assert commands.calls == [("qm", "agent", "201", "network-get-interfaces")]
    assert report.record_outcomes[0].selection_status == "ambiguous"


@pytest.mark.parametrize("failure", ["disabled", "host_timeout", "pve_wait", "malformed"])
def test_failed_metadata_reused_without_poisoning_default_or_ipv4(workspace_dir, failure):
    commands = SyntheticWindowsCommands()
    commands.raw.candidates = commands.raw.candidates[:1]
    add_ipv4(commands)
    if failure == "disabled":
        commands.host_error = "guest-exec is unavailable"
    elif failure == "host_timeout":
        commands.expire = True
    else:
        commands.metadata_output = '{"pid": 123}' if failure == "pve_wait" else "{"
    loaded = load(
        workspace_dir,
        [
            entry(family="both"),
            entry("service"),
            entry("default", "default"),
            entry("other", "default", vmid=202),
        ],
    )
    provider = FakeDNSProvider()
    runner = make_runner(commands, provider)
    report = run(runner, loaded, apply=True)
    v4, strict, service, default, other = report.record_outcomes
    assert v4.selected_value == "8.8.8.8" and v4.applied
    assert strict.status == service.status == "error"
    assert strict.discovery and strict.discovery.error is None
    assert strict.selection and strict.selection.supplementary
    assert default.selected_value == other.selected_value == DHCP
    assert default.applied and other.applied and report.has_errors()
    assert len([c for c in commands.calls if c[1] == "guest"]) == 1
    assert len([c for c in commands.calls if c[1] == "agent"]) == 2
    run(runner, loaded)
    assert len([c for c in commands.calls if c[1] == "guest"]) == 2


def test_private_ipv4_does_not_erase_strict_ipv6_success(workspace_dir):
    commands = SyntheticWindowsCommands()
    add_ipv4(commands, "192.168.1.10")
    loaded = load(workspace_dir, [entry(family="both")])
    provider = FakeDNSProvider()
    v4, v6 = run(make_runner(commands, provider), loaded, apply=True).record_outcomes
    assert v4.status == "skipped" and v4.selected_value is None
    assert v4.selection and v4.selection.filtered_out[0].reason == "private"
    assert v6.selected_value == DHCP and v6.applied
    assert provider.list_records("strict.example.com", "A") == []


@pytest.mark.parametrize("failure", [None, "metadata", "ambiguous", "mismatch"])
@pytest.mark.parametrize("apply", [False, True])
def test_fake_dns_and_prune_safety(workspace_dir: Path, failure, apply) -> None:
    commands = SyntheticWindowsCommands()
    if failure == "metadata":
        commands.metadata_output = '{"pid": 123}'
    elif failure == "ambiguous":
        commands.records[1].update(PrefixOrigin="Dhcp", SuffixOrigin="Dhcp")
    elif failure == "mismatch":
        commands.records.pop(1)
    loaded = load(workspace_dir, [entry()])
    old = DNSRecord(
        provider="cloudflare",
        fqdn="strict.example.com",
        record_type="AAAA",
        value="2001:4860:1234::99",
        record_id="owned",
        ttl=300,
        proxied=False,
    )
    ipv4 = DNSRecord(
        provider="cloudflare",
        fqdn="strict.example.com",
        record_type="A",
        value="8.8.8.8",
        record_id="untracked",
        ttl=300,
        proxied=False,
    )
    provider = FakeDNSProvider([old, ipv4])
    previous = ManagedRecordFile(
        records=[
            ManagedRecordSnapshot(
                workspace_name="lab",
                entry_name="renamed",
                fqdn=old.fqdn,
                record_type="AAAA",
                value=old.value,
                ttl=300,
                record_id="owned",
                state="stale",
                first_managed_at="before",
                last_seen_at="before",
            )
        ]
    )
    report = run(make_runner(commands, provider), loaded, apply=apply, state=previous)
    assert report.prune_outcomes == []
    assert provider.list_records(old.fqdn, "A") == [ipv4]
    if apply and failure is None:
        assert provider.applied_actions == ["update"]
        assert provider.list_records(old.fqdn, "AAAA")[0].value == DHCP
    else:
        assert provider.applied_actions == []
        assert provider.list_records(old.fqdn, "AAAA") == [old]
    if failure == "metadata":
        assert report.has_errors()
    elif failure:
        assert report.record_outcomes[0].status == "skipped"


def test_unknown_policy_fails_before_provider_or_guest_even_for_modified_model(workspace_dir):
    commands = SyntheticWindowsCommands()
    loaded = load(workspace_dir, [entry()])
    loaded.entries_file.entries[0].selection_policy = "typo"

    def forbidden(_):
        pytest.fail("provider must not be constructed for an unsupported policy")

    runner = SyncRunner(
        provider_factory=forbidden,
        discovery_backends={"vm": PVEQGADiscoveryBackend(runner=commands)},
    )
    with pytest.raises(ValueError, match="unsupported selection policy"):
        run(runner, loaded)
    assert commands.calls == []


def test_raw_agent_failure_skips_supplementary_query(workspace_dir):
    from collections.abc import Sequence

    from dnsleaf.util.process import CommandExecutionError, CommandResult

    commands = SyntheticWindowsCommands()

    def stopped(args: Sequence[str], *, check: bool = True, timeout: float | None = None):
        commands.calls.append(tuple(args))
        raise CommandExecutionError(CommandResult(tuple(args), 1, "", "Guest is unavailable"))

    runner = SyncRunner(
        provider_factory=lambda _: FakeDNSProvider(),
        discovery_backends={"vm": PVEQGADiscoveryBackend(runner=stopped)},
        windows_probe=WindowsMetadataProbe(runner=commands),
    )
    loaded = load(workspace_dir, [entry(), entry("service")])
    report = run(runner, loaded)
    assert len(commands.calls) == 1
    assert all(o.status == "error" for o in report.record_outcomes)
    assert all(
        o.discovery and o.discovery.error_stage == "execution" for o in report.record_outcomes
    )
    assert all(o.selection and o.selection.supplementary is None for o in report.record_outcomes)
