from __future__ import annotations

from pathlib import Path

from dnsleaf.discovery.base import DiscoveryBackend
from dnsleaf.discovery.models import AddressCandidate, DiscoveryResult
from dnsleaf.dns.base import DNSProvider
from dnsleaf.dns.models import DNSRecord, PlannedChange, ProviderVerification
from dnsleaf.models import IPAddressFamily, TargetRef
from dnsleaf.systemd import SystemdManager
from dnsleaf.util.process import CommandResult
from dnsleaf.workspace.models import ResolvedWorkspace, SystemdUnitStatus
from dnsleaf.workspace.storage import WorkspacePaths


class FakeDiscoveryBackend(DiscoveryBackend):
    name = "fake_discovery"

    def __init__(self, candidates: list[AddressCandidate] | None = None) -> None:
        self._candidates = candidates or [
            AddressCandidate(
                family=IPAddressFamily.IPV4,
                interface="eth0",
                address="93.184.216.34",
                prefix_length=32,
                source=self.name,
            ),
            AddressCandidate(
                family=IPAddressFamily.IPV6,
                interface="eth0",
                address="2001:4860:abcd:1234::3d6",
                prefix_length=128,
                source=self.name,
            ),
        ]

    def discover(self, target: TargetRef) -> DiscoveryResult:
        return DiscoveryResult(
            target=target,
            backend=self.name,
            candidates=list(self._candidates),
        )


class FakeDNSProvider(DNSProvider):
    name = "cloudflare"

    def __init__(self, initial_records: list[DNSRecord] | None = None) -> None:
        self.applied_actions: list[str] = []
        self._records: dict[tuple[str, str], list[DNSRecord]] = {}
        self._counter = 0
        for record in initial_records or []:
            key = (record.fqdn, record.record_type)
            self._records.setdefault(key, []).append(record)

    def list_records(self, fqdn: str, record_type: str | None = None) -> list[DNSRecord]:
        if record_type is None:
            result: list[DNSRecord] = []
            for (name, _rtype), records in self._records.items():
                if name == fqdn:
                    result.extend(records)
            return list(result)
        return list(self._records.get((fqdn, record_type), []))

    def apply_change(self, change: PlannedChange) -> DNSRecord | None:
        self.applied_actions.append(change.action)
        key = (change.fqdn, change.record_type)
        if change.action == "create":
            assert change.desired is not None
            self._counter += 1
            created = DNSRecord(
                provider=self.name,
                fqdn=change.desired.fqdn,
                record_type=change.desired.record_type,
                value=change.desired.value,
                ttl=change.desired.ttl,
                proxied=change.desired.proxied,
                record_id=f"rec-{self._counter}",
            )
            self._records[key] = [created]
            return created
        if change.action == "update":
            assert change.current is not None
            assert change.desired is not None
            proxied = (
                change.current.proxied if change.desired.proxied is None else change.desired.proxied
            )
            ttl = (
                change.current.ttl
                if change.desired.proxied is None and change.current.proxied is True
                else change.desired.ttl
            )
            updated = DNSRecord(
                provider=self.name,
                fqdn=change.desired.fqdn,
                record_type=change.desired.record_type,
                value=change.desired.value,
                ttl=ttl,
                proxied=proxied,
                record_id=change.current.record_id,
            )
            existing = self._records.get(key, [])
            retained = [
                record for record in existing if record.record_id != change.current.record_id
            ]
            self._records[key] = [updated, *retained]
            return updated
        if change.action == "delete":
            assert change.current is not None
            existing = self._records.get(key, [])
            self._records[key] = [
                record for record in existing if record.record_id != change.current.record_id
            ]
            if not self._records[key]:
                self._records.pop(key, None)
            return None
        return change.current

    def verify(self) -> ProviderVerification:
        return ProviderVerification(
            provider=self.name,
            token_file="/tmp/fake-token.txt",
            zone_id="zone-123",
            zone_name="example.com",
            record_listing_succeeded=True,
        )


class FakeSystemdManager(SystemdManager):
    def __init__(self, unit_dir: Path) -> None:
        self.calls: list[str] = []
        self.unit_dir = unit_dir
        self.installed_units: list[tuple[Path, Path]] = []
        self.daemon_reloaded = False
        self.enabled_timers: list[str] = []
        self.started_services: list[str] = []
        self.stopped_services: list[str] = []
        self.stopped_timers: list[str] = []
        self.disabled_timers: list[str] = []
        self.reset_failed_units: list[tuple[str, str]] = []

    def render_service_unit(self, workspace: ResolvedWorkspace) -> str:
        return (
            "[Service]\n"
            f"ExecStart=dnsleaf sync-once --workspace {workspace.workspace_root} --apply\n"
        )

    def render_timer_unit(self, workspace: ResolvedWorkspace) -> str:
        return f"[Timer]\nUnit={workspace.systemd.service_name}.service\n"

    def install_rendered_units(
        self, paths: WorkspacePaths, workspace: ResolvedWorkspace
    ) -> tuple[Path, Path]:
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        service_path = self.unit_dir / f"{workspace.systemd.service_name}.service"
        timer_path = self.unit_dir / f"{workspace.systemd.timer_name}.timer"
        service_path.write_text("service\n", encoding="utf-8")
        timer_path.write_text("timer\n", encoding="utf-8")
        self.installed_units.append((service_path, timer_path))
        return service_path, timer_path

    def daemon_reload(self, workspace: ResolvedWorkspace, *, check: bool = True) -> CommandResult:
        _ = workspace
        self.daemon_reloaded = True
        return CommandResult(
            args=("systemctl", "daemon-reload"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def enable_restart_timer(self, workspace: ResolvedWorkspace, timer_name: str) -> None:
        _ = workspace
        self.enabled_timers.append(timer_name)

    def start_service(self, workspace: ResolvedWorkspace, service_name: str) -> None:
        _ = workspace
        self.started_services.append(service_name)

    def stop_service(
        self, workspace: ResolvedWorkspace, service_name: str, *, check: bool = False
    ) -> CommandResult:
        self.calls.append("stop_service")
        _ = workspace
        self.stopped_services.append(service_name)
        return CommandResult(
            args=("systemctl", "stop", f"{service_name}.service"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def stop_timer(
        self, workspace: ResolvedWorkspace, timer_name: str, *, check: bool = False
    ) -> CommandResult:
        self.calls.append("stop_timer")
        _ = workspace
        self.stopped_timers.append(timer_name)
        return CommandResult(
            args=("systemctl", "stop", f"{timer_name}.timer"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def disable_timer(
        self,
        workspace: ResolvedWorkspace,
        timer_name: str,
        *,
        check: bool = False,
    ) -> CommandResult:
        self.calls.append("disable_timer")
        _ = workspace
        self.disabled_timers.append(timer_name)
        return CommandResult(
            args=("systemctl", "disable", f"{timer_name}.timer"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def reset_failed(
        self,
        workspace: ResolvedWorkspace,
        unit_name: str,
        unit_kind: str,
        *,
        check: bool = False,
    ) -> CommandResult:
        _ = workspace
        self.reset_failed_units.append((unit_name, unit_kind))
        return CommandResult(
            args=("systemctl", "reset-failed", f"{unit_name}.{unit_kind}"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def installed_unit_path(
        self, workspace: ResolvedWorkspace, unit_name: str, unit_kind: str
    ) -> Path:
        _ = workspace
        return self.unit_dir / f"{unit_name}.{unit_kind}"

    def remove_installed_unit(
        self, workspace: ResolvedWorkspace, unit_name: str, unit_kind: str
    ) -> Path | None:
        path = self.installed_unit_path(workspace, unit_name, unit_kind)
        if not path.exists():
            return None
        path.unlink()
        return path

    def status(
        self, workspace: ResolvedWorkspace, unit_name: str, unit_kind: str
    ) -> SystemdUnitStatus:
        _ = workspace
        return SystemdUnitStatus(
            unit_name=f"{unit_name}.{unit_kind}",
            available=True,
            load_state="loaded",
            unit_file_state="enabled",
            active_state="active",
            sub_state="waiting" if unit_kind == "timer" else "dead",
            fragment_path=str(self.unit_dir / f"{unit_name}.{unit_kind}"),
        )

    def systemctl_available(self, workspace: ResolvedWorkspace) -> bool:
        _ = workspace
        return True

    def unit_dir_writable(self, workspace: ResolvedWorkspace) -> bool:
        _ = workspace
        return True
