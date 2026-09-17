"""PVE QEMU guest agent discovery backend."""

from __future__ import annotations

from dnsleaf.config.shared import DiscoveryConfig
from dnsleaf.discovery.base import DiscoveryBackend
from dnsleaf.discovery.models import DiscoveryResult
from dnsleaf.discovery.parser import parse_qga_interfaces
from dnsleaf.models import TargetKind, TargetRef
from dnsleaf.util.process import ProcessRunner, run_command


class PVEQGADiscoveryBackend(DiscoveryBackend):
    """Discover IPv4 and IPv6 addresses using the QEMU guest agent."""

    name = "pve_qga"

    def __init__(
        self,
        *,
        runner: ProcessRunner = run_command,
        timeout_seconds: float | None = None,
        qm_bin: str = "qm",
    ) -> None:
        self._runner = runner
        self._timeout = (
            DiscoveryConfig.from_defaults().timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self._qm_bin = qm_bin

    def discover(self, target: TargetRef) -> DiscoveryResult:
        if target.kind is not TargetKind.VM:
            raise ValueError("PVEQGADiscoveryBackend only supports vm targets")
        if target.id is None:
            raise ValueError("PVEQGADiscoveryBackend requires a vm target id")

        args = [self._qm_bin, "agent", str(target.id), "network-get-interfaces"]
        try:
            output = self._runner(args, timeout=self._timeout).stdout
            candidates = parse_qga_interfaces(output, source=self.name)
            return DiscoveryResult(target=target, backend=self.name, candidates=candidates)
        except Exception as exc:
            return DiscoveryResult(
                target=target,
                backend=self.name,
                error=str(exc),
            )
