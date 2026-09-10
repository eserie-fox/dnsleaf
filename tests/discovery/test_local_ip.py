from __future__ import annotations

from collections.abc import Sequence

from dnsleaf.discovery.local_ip import LOCAL_DISCOVERY_COMMAND, LocalIPDiscoveryBackend
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.util.process import CommandExecutionError, CommandResult


def test_local_ip_backend_parses_ip_output() -> None:
    sample_output = """
2: eth0    inet 93.184.216.34/32 scope global
2: eth0    inet6 2001:4860:abcd:1234::3d6/128 scope global dynamic mngtmpaddr
""".strip()

    def fake_runner(args: Sequence[str], *, check: bool = True) -> CommandResult:
        assert list(args) == LOCAL_DISCOVERY_COMMAND
        return CommandResult(args=tuple(args), returncode=0, stdout=sample_output, stderr="")

    backend = LocalIPDiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.LOCAL))

    assert result.error is None
    assert [candidate.cidr for candidate in result.candidates] == [
        "93.184.216.34/32",
        "2001:4860:abcd:1234::3d6/128",
    ]


def test_local_ip_backend_rejects_non_local_targets() -> None:
    backend = LocalIPDiscoveryBackend()

    try:
        backend.discover(TargetRef(kind=TargetKind.LXC, id=101))
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert "only supports local targets" in message


def test_local_ip_backend_returns_discovery_error_on_subprocess_failure() -> None:
    def fake_runner(args: Sequence[str], *, check: bool = True) -> CommandResult:
        raise CommandExecutionError(
            CommandResult(args=tuple(args), returncode=1, stdout="", stderr="boom")
        )

    backend = LocalIPDiscoveryBackend(runner=fake_runner)

    result = backend.discover(TargetRef(kind=TargetKind.LOCAL))

    assert result.candidates == []
    assert result.error is not None
    assert "command failed with exit code 1" in result.error
