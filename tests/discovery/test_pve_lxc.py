from __future__ import annotations

from collections.abc import Sequence

from dnsleaf.discovery.parser import parse_ip_addr_output
from dnsleaf.discovery.pve_lxc import PVELXCDiscoveryBackend
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.util.process import CommandResult


def test_pve_lxc_backend_parses_ip_output() -> None:
    sample_output = """
2: eth0    inet 93.184.216.34/32 scope global
2: eth0    inet6 2001:4860:abcd:1234:1111:2222:3333:4444/64 scope global dynamic mngtmpaddr
9: tun0    inet6 fd42:42:42:42::1/112 scope global
""".strip()

    def fake_runner(args: Sequence[str], *, check: bool = True) -> CommandResult:
        assert args[:3] == ["pct", "exec", "101"]
        return CommandResult(args=tuple(args), returncode=0, stdout=sample_output, stderr="")

    backend = PVELXCDiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.LXC, id=101))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == [
        "93.184.216.34/32",
        "2001:4860:abcd:1234:1111:2222:3333:4444/64",
        "fd42:42:42:42::1/112",
    ]
    assert [candidate.family.value for candidate in result.candidates] == [
        "ipv4",
        "ipv6",
        "ipv6",
    ]


def test_pve_lxc_backend_tolerates_wrapped_ip_output_lines() -> None:
    sample_output = """
2: eth0    inet 192.168.100.50/24 metric 1024 brd 192.168.100.255 scope global dynamic eth0\\
       valid_lft 31567sec preferred_lft 31567sec
""".strip()

    def fake_runner(args: Sequence[str], *, check: bool = True) -> CommandResult:
        assert args[:3] == ["pct", "exec", "101"]
        return CommandResult(args=tuple(args), returncode=0, stdout=sample_output, stderr="")

    backend = PVELXCDiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.LXC, id=101))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == ["192.168.100.50/24"]
    assert result.candidates[0].flags == ["dynamic"]


def test_parse_ip_addr_output_handles_multiline_ip_addr_show_style() -> None:
    sample_output = """
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet 93.184.216.34/32 scope global dynamic eth0
       valid_lft 31567sec preferred_lft 31567sec
    inet6 2001:4860:abcd:1234:1111:2222:3333:4444/64 scope global dynamic mngtmpaddr
       valid_lft 31567sec preferred_lft 31567sec
9: tun0: <POINTOPOINT,UP,LOWER_UP> mtu 1500
    inet6 fd42:42:42:42::1/112 scope global
       valid_lft forever preferred_lft forever
""".strip()

    candidates = parse_ip_addr_output(sample_output)

    assert [candidate.cidr for candidate in candidates] == [
        "93.184.216.34/32",
        "2001:4860:abcd:1234:1111:2222:3333:4444/64",
        "fd42:42:42:42::1/112",
    ]
    assert candidates[0].flags == ["dynamic"]
    assert candidates[1].flags == ["dynamic", "mngtmpaddr"]


def test_parse_ip_addr_output_keeps_state_flags_but_ignores_proto_metadata() -> None:
    sample_output = """
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet6 2001:4860:abcd:1234::3d6/128 scope global deprecated dynamic mngtmpaddr
       proto kernel_ra valid_lft 123sec preferred_lft 0sec
    inet6 2001:4860:abcd:1234:1111:2222:3333:4444/64 scope global dynamic mngtmpaddr
       proto kernel_ra valid_lft 31567sec preferred_lft 31567sec
""".strip()

    candidates = parse_ip_addr_output(sample_output)

    assert [candidate.cidr for candidate in candidates] == [
        "2001:4860:abcd:1234::3d6/128",
        "2001:4860:abcd:1234:1111:2222:3333:4444/64",
    ]
    assert candidates[0].flags == ["deprecated", "dynamic", "mngtmpaddr"]
    assert candidates[1].flags == ["dynamic", "mngtmpaddr"]
