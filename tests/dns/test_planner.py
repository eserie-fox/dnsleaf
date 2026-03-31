from __future__ import annotations

from arbor_ddns.dns.models import DesiredRecord, DNSRecord
from arbor_ddns.dns.planner import plan_dns_changes


def test_planner_create_for_aaaa() -> None:
    desired = DesiredRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="AAAA",
        value="2408:8266:5003:506a::3d6",
        ttl=300,
        proxied=False,
    )

    plan = plan_dns_changes(current_records=[], desired_record=desired)

    assert [change.action for change in plan.changes] == ["create"]


def test_planner_update_for_a() -> None:
    desired = DesiredRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="A",
        value="203.0.113.7",
        ttl=300,
        proxied=False,
    )
    current = [
        DNSRecord(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="A",
            value="203.0.113.3",
            ttl=120,
            record_id="rec-1",
            proxied=False,
        )
    ]

    plan = plan_dns_changes(current_records=current, desired_record=desired)

    assert [change.action for change in plan.changes] == ["update"]


def test_planner_delete_when_desired_missing() -> None:
    current = [
        DNSRecord(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            value="2408:8266:5003:506a::111",
            ttl=120,
            record_id="rec-1",
            proxied=False,
        )
    ]

    plan = plan_dns_changes(current_records=current, desired_record=None)

    assert [change.action for change in plan.changes] == ["delete"]


def test_planner_noop_when_already_in_sync() -> None:
    desired = DesiredRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="AAAA",
        value="2408:8266:5003:506a::3d6",
        ttl=300,
        proxied=False,
    )
    current = [
        DNSRecord(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            value="2408:8266:5003:506a::3d6",
            ttl=300,
            record_id="rec-1",
            proxied=False,
        )
    ]

    plan = plan_dns_changes(current_records=current, desired_record=desired)

    assert [change.action for change in plan.changes] == ["noop"]
