from __future__ import annotations

from arbor_ddns.discovery.pve_lxc import PVELXCDiscoveryBackend
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.util.process import CommandResult


def test_pve_lxc_backend_parses_ip_output() -> None:
    sample_output = """
2: eth0    inet6 2408:8266:5003:506a:be24:11ff:fefb:7700/64 scope global dynamic mngtmpaddr
9: tun0    inet6 fd42:42:42:42::1/112 scope global
""".strip()

    def fake_runner(args):
        assert args[:3] == ["pct", "exec", "101"]
        return CommandResult(args=tuple(args), returncode=0, stdout=sample_output, stderr="")

    backend = PVELXCDiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.LXC, id=101))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == [
        "2408:8266:5003:506a:be24:11ff:fefb:7700/64",
        "fd42:42:42:42::1/112",
    ]

