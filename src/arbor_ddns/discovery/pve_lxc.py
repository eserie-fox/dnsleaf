"""PVE LXC discovery backend."""

from __future__ import annotations

from arbor_ddns.discovery.base import DiscoveryBackend
from arbor_ddns.discovery.models import DiscoveryResult
from arbor_ddns.discovery.parser import parse_ip_addr_output
from arbor_ddns.models import TargetKind, TargetRef
from arbor_ddns.util.process import ProcessRunner, run_command

LXC_DISCOVERY_COMMAND = "ip -o addr show"


class PVELXCDiscoveryBackend(DiscoveryBackend):
    """Discover IPv4 and IPv6 addresses by executing `ip` inside an LXC guest."""

    name = "pve_lxc"

    def __init__(
        self,
        *,
        runner: ProcessRunner = run_command,
        pct_bin: str = "pct",
        shell_bin: str = "sh",
    ) -> None:
        self._runner = runner
        self._pct_bin = pct_bin
        self._shell_bin = shell_bin

    def discover(self, target: TargetRef) -> DiscoveryResult:
        if target.kind is not TargetKind.LXC:
            raise ValueError("PVELXCDiscoveryBackend only supports lxc targets")
        if target.id is None:
            raise ValueError("PVELXCDiscoveryBackend requires an lxc target id")

        args = [
            self._pct_bin,
            "exec",
            str(target.id),
            "--",
            self._shell_bin,
            "-lc",
            LXC_DISCOVERY_COMMAND,
        ]
        try:
            output = self._runner(args).stdout
            candidates = parse_ip_addr_output(output, source=self.name)
            return DiscoveryResult(target=target, backend=self.name, candidates=candidates)
        except Exception as exc:
            return DiscoveryResult(target=target, backend=self.name, error=str(exc))
