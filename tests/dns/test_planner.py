from __future__ import annotations

from dnsleaf.dns.models import DesiredRecord, DNSRecord
from dnsleaf.dns.planner import plan_dns_changes


def test_planner_create_for_aaaa() -> None:
    desired = DesiredRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="AAAA",
        value="2001:4860:abcd:1234::3d6",
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
            value="2001:4860:abcd:1234::111",
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
        value="2001:4860:abcd:1234::3d6",
        ttl=300,
        proxied=False,
    )
    current = [
        DNSRecord(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            value="2001:4860:abcd:1234::3d6",
            ttl=300,
            record_id="rec-1",
            proxied=False,
        )
    ]

    plan = plan_dns_changes(current_records=current, desired_record=desired)

    assert [change.action for change in plan.changes] == ["noop"]


def test_planner_noops_when_proxy_is_unmanaged_and_cloudflare_forces_auto_ttl() -> None:
    desired = DesiredRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="AAAA",
        value="2001:4860:abcd:1234::3d6",
        ttl=300,
        proxied=None,
    )
    current = [
        DNSRecord(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            value="2001:4860:abcd:1234::3d6",
            ttl=1,
            record_id="rec-1",
            proxied=True,
        )
    ]

    plan = plan_dns_changes(current_records=current, desired_record=desired)

    assert [change.action for change in plan.changes] == ["noop"]


def test_planner_updates_when_proxied_is_explicitly_enabled() -> None:
    desired = DesiredRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="AAAA",
        value="2001:4860:abcd:1234::3d6",
        ttl=1,
        proxied=True,
    )
    current = [
        DNSRecord(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            value="2001:4860:abcd:1234::3d6",
            ttl=120,
            record_id="rec-1",
            proxied=False,
        )
    ]

    plan = plan_dns_changes(current_records=current, desired_record=desired)

    assert [change.action for change in plan.changes] == ["update"]


def test_planner_updates_when_proxied_is_explicitly_disabled() -> None:
    desired = DesiredRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="AAAA",
        value="2001:4860:abcd:1234::3d6",
        ttl=300,
        proxied=False,
    )
    current = [
        DNSRecord(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            value="2001:4860:abcd:1234::3d6",
            ttl=1,
            record_id="rec-1",
            proxied=True,
        )
    ]

    plan = plan_dns_changes(current_records=current, desired_record=desired)

    assert [change.action for change in plan.changes] == ["update"]


def test_planner_refuses_ambiguous_remote_records_including_exact_match() -> None:
    import pytest

    desired = DesiredRecord(
        provider="cloudflare",
        fqdn="host.example.com",
        record_type="A",
        value="192.0.2.1",
        ttl=120,
        proxied=None,
    )
    first = DNSRecord(
        provider="cloudflare",
        fqdn=desired.fqdn,
        record_type="A",
        value="192.0.2.1",
        ttl=120,
        record_id="one",
    )
    second = first.model_copy(update={"value": "192.0.2.2", "record_id": "two"})
    for target in [desired, desired.model_copy(update={"value": "192.0.2.3"})]:
        with pytest.raises(ValueError, match="refusing to choose or delete"):
            plan_dns_changes(current_records=[first, second], desired_record=target)
