"""Workspace rendering service."""

from __future__ import annotations

from dnsleaf.systemd import SystemdManager
from dnsleaf.workspace.reports import DesiredRecordSpec, RenderArtifacts
from dnsleaf.workspace.storage import LoadedWorkspace, atomic_write_text, dump_json_data


class WorkspaceRenderer:
    """Generate rendered workspace artifacts without applying them."""

    def __init__(self, systemd_manager: SystemdManager | None = None) -> None:
        self._systemd_manager = systemd_manager or SystemdManager()

    def render(self, loaded: LoadedWorkspace) -> RenderArtifacts:
        """Render effective config, desired-record specs, and systemd units."""

        desired_records = [
            spec
            for entry in loaded.entries_file.entries
            for spec in DesiredRecordSpec.from_entry(
                workspace=loaded.resolved_workspace,
                entry=entry,
            )
        ]
        dump_json_data(
            loaded.paths.effective_workspace_file,
            loaded.resolved_workspace.model_dump(mode="json"),
        )
        dump_json_data(
            loaded.paths.desired_records_file,
            {
                "workspace_name": loaded.resolved_workspace.workspace_name,
                "records": [record.render_mapping() for record in desired_records],
            },
        )

        service_name = loaded.resolved_workspace.systemd.service_name
        timer_name = loaded.resolved_workspace.systemd.timer_name
        service_path = loaded.paths.rendered_systemd_dir / f"{service_name}.service"
        timer_path = loaded.paths.rendered_systemd_dir / f"{timer_name}.timer"
        atomic_write_text(
            service_path,
            self._systemd_manager.render_service_unit(loaded.resolved_workspace),
        )
        atomic_write_text(
            timer_path,
            self._systemd_manager.render_timer_unit(loaded.resolved_workspace),
        )

        return RenderArtifacts(
            workspace_root=str(loaded.paths.root),
            workspace_name=loaded.resolved_workspace.workspace_name,
            effective_workspace_file=str(loaded.paths.effective_workspace_file),
            desired_records_file=str(loaded.paths.desired_records_file),
            service_unit_file=str(service_path),
            timer_unit_file=str(timer_path),
            desired_record_count=len(desired_records),
        )
