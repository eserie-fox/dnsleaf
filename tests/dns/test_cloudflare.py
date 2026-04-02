from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from arbor_ddns.dns.cloudflare import (
    CloudflareAPIError,
    CloudflareAuthenticationError,
    CloudflareConflictError,
    CloudflareDNSProvider,
    CloudflareNetworkError,
    CloudflarePermissionError,
    CloudflareProviderConfig,
)
from arbor_ddns.dns.models import DesiredRecord, DNSRecord, PlannedChange


def _token_file(tmp_path: Path, content: str = "secret-token\n") -> Path:
    path = tmp_path / "cloudflare_token.txt"
    path.write_text(content, encoding="utf-8")
    return path


def _config(tmp_path: Path, **overrides: object) -> CloudflareProviderConfig:
    data: dict[str, object] = {
        "enabled": True,
        "zone_name": "example.com",
        "zone_id": None,
        "api_token_file": str(_token_file(tmp_path)),
        "timeout_seconds": 10.0,
        "proxied": False,
        "ttl": 120,
    }
    data.update(overrides)
    return CloudflareProviderConfig.model_validate(data)


def _response_json(payload: dict[str, object], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload)


def test_provider_reads_and_strips_token_file(tmp_path: Path) -> None:
    config = _config(tmp_path)

    assert config.resolved_api_token() == "secret-token"


def test_provider_uses_direct_zone_id_without_zone_lookup(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/client/v4/zones/zone-123/dns_records"
        return _response_json({"success": True, "result": []})

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.list_records("host.example.com", "AAAA") == []
    assert len(requests) == 1


def test_provider_resolves_zone_name_and_caches_zone_id(tmp_path: Path) -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/client/v4/zones":
            return _response_json(
                {
                    "success": True,
                    "result": [{"id": "zone-123", "name": "example.com"}],
                }
            )
        if request.url.path == "/client/v4/zones/zone-123/dns_records":
            return _response_json({"success": True, "result": []})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.list_records("host.example.com", "AAAA")
    provider.list_records("host.example.com", "AAAA")

    assert requests.count(("GET", "/client/v4/zones")) == 1


def test_provider_lists_records_and_maps_response(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/client/v4/zones":
            return _response_json(
                {"success": True, "result": [{"id": "zone-123", "name": "example.com"}]}
            )
        return _response_json(
            {
                "success": True,
                "result": [
                    {
                        "id": "rec-1",
                        "type": "AAAA",
                        "name": "host.example.com",
                        "content": "2408:8266:5003:506a::3d6",
                        "ttl": 120,
                        "proxied": False
                    }
                ],
            }
        )

    provider = CloudflareDNSProvider(
        _config(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    records = provider.list_records("host.example.com", "AAAA")

    assert records == [
        DNSRecord(
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            value="2408:8266:5003:506a::3d6",
            ttl=120,
            record_id="rec-1",
            proxied=False,
        )
    ]


def test_provider_builds_create_request(tmp_path: Path) -> None:
    post_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/client/v4/zones":
            return _response_json(
                {"success": True, "result": [{"id": "zone-123", "name": "example.com"}]}
            )
        if request.method == "GET":
            return _response_json({"success": True, "result": []})
        if request.method == "POST":
            post_payloads.append(json.loads(request.content.decode("utf-8")))
            return _response_json(
                {
                    "success": True,
                    "result": {
                        "id": "rec-1",
                        "type": "A",
                        "name": "host.example.com",
                        "content": "203.0.113.7",
                        "ttl": 120,
                        "proxied": False
                    },
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    created = provider.apply_change(
        PlannedChange(
            action="create",
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="A",
            desired=DesiredRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="A",
                value="203.0.113.7",
                ttl=120,
                proxied=False,
            ),
            reason="test create",
        )
    )

    assert created is not None
    assert post_payloads == [
        {
            "type": "A",
            "name": "host.example.com",
            "content": "203.0.113.7",
            "ttl": 120,
            "proxied": False,
        }
    ]


def test_provider_create_omits_unmanaged_proxied_and_sends_auto_ttl(tmp_path: Path) -> None:
    post_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/client/v4/zones":
            return _response_json(
                {"success": True, "result": [{"id": "zone-123", "name": "example.com"}]}
            )
        if request.method == "GET":
            return _response_json({"success": True, "result": []})
        if request.method == "POST":
            post_payloads.append(json.loads(request.content.decode("utf-8")))
            return _response_json(
                {
                    "success": True,
                    "result": {
                        "id": "rec-1",
                        "type": "AAAA",
                        "name": "host.example.com",
                        "content": "2408:8266:5003:506a::3d6",
                        "ttl": 1,
                        "proxied": False,
                    },
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    created = provider.apply_change(
        PlannedChange(
            action="create",
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            desired=DesiredRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                value="2408:8266:5003:506a::3d6",
                ttl=1,
                proxied=None,
            ),
            reason="test create unmanaged proxied",
        )
    )

    assert created is not None
    assert post_payloads == [
        {
            "type": "AAAA",
            "name": "host.example.com",
            "content": "2408:8266:5003:506a::3d6",
            "ttl": 1,
        }
    ]


def test_provider_builds_update_request(tmp_path: Path) -> None:
    patch_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            patch_payloads.append(json.loads(request.content.decode("utf-8")))
            return _response_json(
                {
                    "success": True,
                    "result": {
                        "id": "rec-1",
                        "type": "AAAA",
                        "name": "host.example.com",
                        "content": "2408:8266:5003:506a::3d6",
                        "ttl": 120,
                        "proxied": False
                    },
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    updated = provider.apply_change(
        PlannedChange(
            action="update",
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            current=DNSRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                value="2408:8266:5003:506a::111",
                ttl=300,
                record_id="rec-1",
                proxied=False,
            ),
            desired=DesiredRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                value="2408:8266:5003:506a::3d6",
                ttl=120,
                proxied=False,
            ),
            reason="test update",
        )
    )

    assert updated is not None
    assert patch_payloads == [{"content": "2408:8266:5003:506a::3d6", "ttl": 120}]


def test_provider_update_omits_unmanaged_proxied_and_ignores_forced_auto_ttl(
    tmp_path: Path,
) -> None:
    patch_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            patch_payloads.append(json.loads(request.content.decode("utf-8")))
            return _response_json(
                {
                    "success": True,
                    "result": {
                        "id": "rec-1",
                        "type": "AAAA",
                        "name": "host.example.com",
                        "content": "2408:8266:5003:506a::3d6",
                        "ttl": 1,
                        "proxied": True,
                    },
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    updated = provider.apply_change(
        PlannedChange(
            action="update",
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            current=DNSRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                value="2408:8266:5003:506a::111",
                ttl=1,
                record_id="rec-1",
                proxied=True,
            ),
            desired=DesiredRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                value="2408:8266:5003:506a::3d6",
                ttl=300,
                proxied=None,
            ),
            reason="test update unmanaged proxied",
        )
    )

    assert updated is not None
    assert patch_payloads == [{"content": "2408:8266:5003:506a::3d6"}]


def test_provider_update_explicit_proxied_true_uses_auto_ttl(tmp_path: Path) -> None:
    patch_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            patch_payloads.append(json.loads(request.content.decode("utf-8")))
            return _response_json(
                {
                    "success": True,
                    "result": {
                        "id": "rec-1",
                        "type": "A",
                        "name": "host.example.com",
                        "content": "203.0.113.7",
                        "ttl": 1,
                        "proxied": True,
                    },
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    updated = provider.apply_change(
        PlannedChange(
            action="update",
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="A",
            current=DNSRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="A",
                value="203.0.113.7",
                ttl=120,
                record_id="rec-1",
                proxied=False,
            ),
            desired=DesiredRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="A",
                value="203.0.113.7",
                ttl=1,
                proxied=True,
            ),
            reason="test explicit proxied true",
        )
    )

    assert updated is not None
    assert patch_payloads == [{"ttl": 1, "proxied": True}]


def test_provider_builds_delete_request(tmp_path: Path) -> None:
    seen_delete_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            seen_delete_paths.append(request.url.path)
            return _response_json({"success": True, "result": {"id": "rec-1"}})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.apply_change(
        PlannedChange(
            action="delete",
            provider="cloudflare",
            fqdn="host.example.com",
            record_type="AAAA",
            current=DNSRecord(
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                value="2408:8266:5003:506a::3d6",
                ttl=120,
                record_id="rec-1",
                proxied=False,
            ),
            reason="test delete",
        )
    )

    assert seen_delete_paths == ["/client/v4/zones/zone-123/dns_records/rec-1"]


def test_provider_raises_on_api_failure(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response_json(
            {
                "success": False,
                "errors": [{"code": 10000, "message": "authentication failed"}],
                "messages": [],
            },
            status_code=403,
        )

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudflareAuthenticationError):
        provider.list_records("host.example.com", "AAAA")


def test_provider_raises_on_network_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudflareNetworkError):
        provider.list_records("host.example.com", "AAAA")


def test_provider_raises_clear_cname_conflict(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/client/v4/zones":
            return _response_json(
                {"success": True, "result": [{"id": "zone-123", "name": "example.com"}]}
            )
        if request.method == "GET":
            return _response_json(
                {
                    "success": True,
                    "result": [
                        {
                            "id": "rec-cname",
                            "type": "CNAME",
                            "name": "host.example.com",
                            "content": "other.example.com",
                            "ttl": 120
                        }
                    ],
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudflareConflictError):
        provider.apply_change(
            PlannedChange(
                action="create",
                provider="cloudflare",
                fqdn="host.example.com",
                record_type="AAAA",
                desired=DesiredRecord(
                    provider="cloudflare",
                    fqdn="host.example.com",
                    record_type="AAAA",
                    value="2408:8266:5003:506a::3d6",
                    ttl=120,
                    proxied=False,
                ),
                reason="conflict test",
            )
        )


def test_provider_wraps_unexpected_api_failure(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response_json(
            {
                "success": False,
                "errors": [{"code": 9000, "message": "generic failure"}],
                "messages": [],
            },
            status_code=400,
        )

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudflareAPIError):
        provider.list_records("host.example.com", "AAAA")


def test_provider_verify_checks_zone_and_record_listing(tmp_path: Path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/client/v4/zones":
            return _response_json(
                {"success": True, "result": [{"id": "zone-123", "name": "example.com"}]}
            )
        if request.url.path == "/client/v4/zones/zone-123/dns_records":
            return _response_json({"success": True, "result": []})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    provider = CloudflareDNSProvider(
        _config(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    verification = provider.verify()

    assert verification.zone_id == "zone-123"
    assert verification.zone_name == "example.com"
    assert verification.record_listing_succeeded is True
    assert requests == [
        "/client/v4/zones",
        "/client/v4/zones/zone-123/dns_records",
    ]


def test_provider_raises_permission_error_on_non_auth_403(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response_json(
            {
                "success": False,
                "errors": [{"code": 9109, "message": "missing dns edit permission"}],
                "messages": [],
            },
            status_code=403,
        )

    provider = CloudflareDNSProvider(
        _config(tmp_path, zone_id="zone-123", zone_name=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CloudflarePermissionError):
        provider.list_records("host.example.com", "AAAA")
