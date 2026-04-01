from __future__ import annotations

from collections.abc import Sequence

from arbor_ddns.discovery.parser import parse_ip_addr_output, parse_lxc_ip_addr_output
from arbor_ddns.discovery.pve_lxc import PVELXCDiscoveryBackend
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.util.process import CommandResult


def test_pve_lxc_backend_parses_ip_output() -> None:
    sample_output = """
2: eth0    inet 93.184.216.34/32 scope global
2: eth0    inet6 2408:8266:5003:506a:be24:11ff:fefb:7700/64 scope global dynamic mngtmpaddr
9: tun0    inet6 fd42:42:42:42::1/112 scope global
""".strip()

    def fake_runner(args: Sequence[str]) -> CommandResult:
        assert args[:3] == ["pct", "exec", "101"]
        return CommandResult(args=tuple(args), returncode=0, stdout=sample_output, stderr="")

    backend = PVELXCDiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.LXC, id=101))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == [
        "93.184.216.34/32",
        "2408:8266:5003:506a:be24:11ff:fefb:7700/64",
        "fd42:42:42:42::1/112",
    ]
    assert [candidate.family.value for candidate in result.candidates] == [
        "ipv4",
        "ipv6",
        "ipv6",
    ]


def test_pve_lxc_backend_tolerates_wrapped_ip_output_lines() -> None:
    sample_output = """
2: eth0    inet 192.168.37.50/24 metric 1024 brd 192.168.37.255 scope global dynamic eth0\\
       valid_lft 31567sec preferred_lft 31567sec
""".strip()

    def fake_runner(args: Sequence[str]) -> CommandResult:
        assert args[:3] == ["pct", "exec", "101"]
        return CommandResult(args=tuple(args), returncode=0, stdout=sample_output, stderr="")

    backend = PVELXCDiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.LXC, id=101))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == ["192.168.37.50/24"]
    assert result.candidates[0].flags == ["dynamic"]


def test_parse_ip_addr_output_handles_multiline_ip_addr_show_style() -> None:
    sample_output = """
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet 93.184.216.34/32 scope global dynamic eth0
       valid_lft 31567sec preferred_lft 31567sec
    inet6 2408:8266:5003:506a:be24:11ff:fefb:7700/64 scope global dynamic mngtmpaddr
       valid_lft 31567sec preferred_lft 31567sec
9: tun0: <POINTOPOINT,UP,LOWER_UP> mtu 1500
    inet6 fd42:42:42:42::1/112 scope global
       valid_lft forever preferred_lft forever
""".strip()

    candidates = parse_ip_addr_output(sample_output)

    assert [candidate.cidr for candidate in candidates] == [
        "93.184.216.34/32",
        "2408:8266:5003:506a:be24:11ff:fefb:7700/64",
        "fd42:42:42:42::1/112",
    ]
    assert candidates[0].flags == ["dynamic"]
    assert candidates[1].flags == ["dynamic", "mngtmpaddr"]
    assert parse_lxc_ip_addr_output(sample_output) == parse_ip_addr_output(
        sample_output,
        source="pve_lxc",
    )
