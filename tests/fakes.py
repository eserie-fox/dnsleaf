from __future__ import annotations

from pathlib import Path

from arbor_ddns.discovery.base import DiscoveryBackend
from arbor_ddns.discovery.models import AddressCandidate, DiscoveryResult
from arbor_ddns.dns.base import DNSProvider
from arbor_ddns.dns.models import DNSRecord, PlannedChange, ProviderVerification
from arbor_ddns.models import TargetRef
from arbor_ddns.util.process import CommandResult
from arbor_ddns.workspace.models import SystemdUnitStatus
from arbor_ddns.workspace.storage import WorkspacePaths


class FakeDiscoveryBackend(DiscoveryBackend):
    name = "fake_discovery"

    def discover(self, target: TargetRef) -> DiscoveryResult:
        return DiscoveryResult(
            target=target,
            backend=self.name,
            candidates=[
                AddressCandidate(
                    interface="eth0",
                    address="2408:8266:5003:506a::3d6",
                    prefix_length=128,
                    source=self.name,
                )
            ],
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
            updated = DNSRecord(
                provider=self.name,
                fqdn=change.desired.fqdn,
                record_type=change.desired.record_type,
                value=change.desired.value,
                ttl=change.desired.ttl,
                proxied=change.desired.proxied,
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


class FakeSystemdManager:
    def __init__(self, unit_dir: Path) -> None:
        self.unit_dir = unit_dir
        self.installed_units: list[tuple[Path, Path]] = []
        self.daemon_reloaded = False
        self.enabled_timers: list[str] = []
        self.started_services: list[str] = []
        self.stopped_services: list[str] = []
        self.stopped_timers: list[str] = []
        self.disabled_timers: list[str] = []

    def render_service_unit(self, workspace) -> str:
        return (
            "[Service]\n"
            f"ExecStart=arbor-ddns sync-once --workspace {workspace.workspace_root} --apply\n"
        )

    def render_timer_unit(self, workspace) -> str:
        return f"[Timer]\nUnit={workspace.systemd.service_name}.service\n"

    def install_rendered_units(self, paths: WorkspacePaths, workspace) -> tuple[Path, Path]:
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        service_path = self.unit_dir / f"{workspace.systemd.service_name}.service"
        timer_path = self.unit_dir / f"{workspace.systemd.timer_name}.timer"
        service_path.write_text("service\n", encoding="utf-8")
        timer_path.write_text("timer\n", encoding="utf-8")
        self.installed_units.append((service_path, timer_path))
        return service_path, timer_path

    def daemon_reload(self, *, check: bool = True) -> CommandResult:
        self.daemon_reloaded = True
        return CommandResult(
            args=("systemctl", "daemon-reload"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def enable_restart_timer(self, timer_name: str) -> None:
        self.enabled_timers.append(timer_name)

    def start_service(self, service_name: str) -> None:
        self.started_services.append(service_name)

    def stop_service(self, service_name: str, *, check: bool = False) -> CommandResult:
        self.stopped_services.append(service_name)
        return CommandResult(
            args=("systemctl", "stop", f"{service_name}.service"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def stop_timer(self, timer_name: str, *, check: bool = False) -> CommandResult:
        self.stopped_timers.append(timer_name)
        return CommandResult(
            args=("systemctl", "stop", f"{timer_name}.timer"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def disable_timer(self, timer_name: str, *, check: bool = False) -> CommandResult:
        self.disabled_timers.append(timer_name)
        return CommandResult(
            args=("systemctl", "disable", f"{timer_name}.timer"),
            returncode=0,
            stdout="",
            stderr="",
        )

    def installed_unit_path(self, unit_name: str, unit_kind: str) -> Path:
        return self.unit_dir / f"{unit_name}.{unit_kind}"

    def remove_installed_unit(self, unit_name: str, unit_kind: str) -> Path | None:
        path = self.installed_unit_path(unit_name, unit_kind)
        if not path.exists():
            return None
        path.unlink()
        return path

    def status(self, unit_name: str, unit_kind: str) -> SystemdUnitStatus:
        return SystemdUnitStatus(
            unit_name=f"{unit_name}.{unit_kind}",
            available=True,
            load_state="loaded",
            unit_file_state="enabled",
            active_state="active",
            sub_state="waiting" if unit_kind == "timer" else "dead",
            fragment_path=str(self.unit_dir / f"{unit_name}.{unit_kind}"),
        )

    def systemctl_available(self) -> bool:
        return True

    def unit_dir_writable(self) -> bool:
        return True
