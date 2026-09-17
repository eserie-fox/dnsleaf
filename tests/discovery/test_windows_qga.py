"""Synthetic standard-QGA Windows fixtures; no live Windows/PVE acceptance implied."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence

import pytest

from dnsleaf.discovery.local_ip import LocalIPDiscoveryBackend
from dnsleaf.discovery.models import DiscoveryResult
from dnsleaf.discovery.parser import parse_qga_interfaces
from dnsleaf.discovery.pve_lxc import PVELXCDiscoveryBackend
from dnsleaf.discovery.pve_qga import PVEQGADiscoveryBackend
from dnsleaf.discovery.selectors import select_address
from dnsleaf.models import IPAddressFamily, TargetKind, TargetRef
from dnsleaf.util.process import (
    CommandExecutionError,
    CommandNotFoundError,
    CommandResult,
    run_command,
)


def address(value: str, kind: str = "ipv6", prefix: int = 64) -> dict[str, object]:
    return {"ip-address": value, "ip-address-type": kind, "prefix": prefix}


def windows_interfaces() -> list[dict[str, object]]:
    return [
        {"name": "Loopback Pseudo-Interface 1", "ip-addresses": [address("::1", prefix=128)]},
        {
            "name": "Ethernet 适配器",
            "hardware-address": "52:54:00:12:34:56",
            "ip-addresses": [
                address("fe80::1234%12"),
                address("fd12::1"),
                address("192.168.1.10", "ipv4", 24),
                address("169.254.1.2", "ipv4", 16),
                address("127.0.0.1", "ipv4", 8),
                address("8.8.8.8", "ipv4", 32),
                address("2001:4860:1::100", prefix=128),
            ],
        },
        {"name": "Ethernet 2", "ip-addresses": [address("2001:4860:2::200")]},
        {"name": "Bluetooth Network Connection"},
    ]


@pytest.mark.parametrize("wrapper", [None, "result", "return"])
def test_windows_standard_wrappers_conservative_selection(wrapper: str | None) -> None:
    payload = windows_interfaces()
    candidates = parse_qga_interfaces(json.dumps({wrapper: payload} if wrapper else payload))
    assert any(c.interface == "Ethernet 适配器" for c in candidates)
    assert all("%" not in c.address for c in candidates)
    result = DiscoveryResult(
        target=TargetRef(kind=TargetKind.VM, id=101), backend="pve_qga", candidates=candidates
    )
    original = result.model_dump()
    v6 = select_address(result, family=IPAddressFamily.IPV6)
    v4 = select_address(result, family=IPAddressFamily.IPV4)
    assert v6.selected and v6.selected.address == "2001:4860:1::100"
    assert v4.selected and v4.selected.address == "8.8.8.8"
    assert {c.reason for c in v6.filtered_out} >= {"loopback", "link_local", "unique_local"}
    assert result.model_dump() == original


def test_multiple_windows_adapters_remain_ambiguous() -> None:
    candidates = parse_qga_interfaces(
        [
            {"name": "Ethernet 1", "ip-addresses": [address("2001:4860:1::1", prefix=128)]},
            {"name": "以太网 2", "ip-addresses": [address("2001:4860:2::2", prefix=128)]},
        ]
    )
    result = DiscoveryResult(
        target=TargetRef(kind=TargetKind.VM, id=101), backend="pve_qga", candidates=candidates
    )
    selection = select_address(result, family=IPAddressFamily.IPV6)
    assert selection.status == "ambiguous" and selection.selected is None
    assert len(selection.remaining_candidates) == 2


@pytest.mark.parametrize("payload", ["{", "null", "{}", '{"result": {}}'])
def test_bad_protocol_response_is_discovery_error(payload: str) -> None:
    def fake(args: Sequence[str], *, check: bool = True, timeout: float | None = None):
        return CommandResult(tuple(args), 0, payload, "")

    result = PVEQGADiscoveryBackend(runner=fake).discover(TargetRef(kind=TargetKind.VM, id=101))
    assert result.error and result.candidates == []
    assert "sudo" not in result.error


def test_invalid_address_items_do_not_become_dns_candidates() -> None:
    candidates = parse_qga_interfaces(
        [
            {
                "name": "Ethernet 适配器",
                "ip-addresses": [
                    None,
                    [],
                    {},
                    address("not-an-ip"),
                    address("::1", prefix=129),
                    address("8.8.8.8", "ipv6", 32),
                    address("2001:4860::1%4"),
                    {"ip-address-type": [], "ip-address": "::1", "prefix": 64},
                    {"ip-address-type": "ipv6", "ip-address": "::1", "prefix": True},
                    address("2001:4860::10", prefix=128),
                ],
            }
        ]
    )
    assert [c.address for c in candidates] == ["2001:4860::10"]


@pytest.mark.parametrize(
    "message", ["VM 101 is not running", "QEMU guest agent unavailable", "代理不可用"]
)
def test_guest_failure_retains_command_context_without_guessing(message: str) -> None:
    def fake(args: Sequence[str], *, check: bool = True, timeout: float | None = None):
        raise CommandExecutionError(CommandResult(tuple(args), 1, "", message))

    result = PVEQGADiscoveryBackend(runner=fake).discover(TargetRef(kind=TargetKind.VM, id=101))
    assert result.error and message in result.error
    assert "qm agent 101 network-get-interfaces" in result.error
    assert "sudo" not in result.error


def test_missing_qm_is_execution_failure() -> None:
    def fake(args: Sequence[str], *, check: bool = True, timeout: float | None = None):
        raise CommandNotFoundError(args[0])

    result = PVEQGADiscoveryBackend(runner=fake).discover(TargetRef(kind=TargetKind.VM, id=101))
    assert result.error == "command not found: qm"


@pytest.mark.parametrize(
    "backend,kind",
    [
        (LocalIPDiscoveryBackend, TargetKind.LOCAL),
        (PVELXCDiscoveryBackend, TargetKind.LXC),
        (PVEQGADiscoveryBackend, TargetKind.VM),
    ],
)
def test_discovery_subprocess_timeout_is_bounded(monkeypatch, backend, kind) -> None:
    calls = []

    def expired(args, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", expired)
    target = TargetRef(kind=kind, id=None if kind is TargetKind.LOCAL else 101)
    result = backend(runner=run_command, timeout_seconds=7).discover(target)
    assert calls[0]["timeout"] == 7
    assert result.error and "timed out after 7 seconds" in result.error
    assert result.candidates == []


def test_unrelated_processes_keep_no_timeout(monkeypatch) -> None:
    def fake(args, **kwargs):
        assert kwargs["timeout"] is None
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("subprocess.run", fake)
    assert run_command(["systemctl", "stop", "test.service"]).returncode == 0
