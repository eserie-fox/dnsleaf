"""Host-local IP discovery backend."""

from __future__ import annotations

from dnsleaf.discovery.base import DiscoveryBackend
from dnsleaf.discovery.models import DiscoveryResult
from dnsleaf.discovery.parser import parse_ip_addr_output
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.util.process import ProcessRunner, run_command

LOCAL_DISCOVERY_COMMAND = ["ip", "-o", "addr", "show"]


class LocalIPDiscoveryBackend(DiscoveryBackend):
    """Discover IPv4 and IPv6 addresses from the local host."""

    name = "local_ip"

    def __init__(
        self,
        *,
        runner: ProcessRunner = run_command,
    ) -> None:
        self._runner = runner

    def discover(self, target: TargetRef) -> DiscoveryResult:
        if target.kind is not TargetKind.LOCAL:
            raise ValueError("LocalIPDiscoveryBackend only supports local targets")

        try:
            output = self._runner(LOCAL_DISCOVERY_COMMAND).stdout
            candidates = parse_ip_addr_output(output, source=self.name)
            return DiscoveryResult(target=target, backend=self.name, candidates=candidates)
        except Exception as exc:
            return DiscoveryResult(target=target, backend=self.name, error=str(exc))
