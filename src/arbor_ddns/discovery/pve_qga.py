"""PVE QEMU guest agent discovery backend."""

from __future__ import annotations

from arbor_ddns.discovery.base import DiscoveryBackend
from arbor_ddns.discovery.models import DiscoveryResult
from arbor_ddns.discovery.parser import parse_qga_interfaces
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.util.process import ProcessRunner, run_command


class PVEQGADiscoveryBackend(DiscoveryBackend):
    """Discover IPv4 and IPv6 addresses using the QEMU guest agent."""

    name = "pve_qga"

    def __init__(
        self,
        *,
        runner: ProcessRunner = run_command,
        qm_bin: str = "qm",
    ) -> None:
        self._runner = runner
        self._qm_bin = qm_bin

    def discover(self, target: TargetRef) -> DiscoveryResult:
        if target.kind is not TargetKind.VM:
            raise ValueError("PVEQGADiscoveryBackend only supports vm targets")

        args = [self._qm_bin, "agent", str(target.id), "network-get-interfaces"]
        try:
            output = self._runner(args).stdout
            candidates = parse_qga_interfaces(output, source=self.name)
            return DiscoveryResult(target=target, backend=self.name, candidates=candidates)
        except Exception as exc:
            return DiscoveryResult(target=target, backend=self.name, error=str(exc))
