"""Cloudflare DNS provider implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arbor_ddns.dns.base import DNSProvider
from arbor_ddns.dns.models import DesiredRecord, DNSRecord, PlannedChange, ProviderVerification

API_BASE_URL = "https://api.cloudflare.com/client/v4"


class CloudflareProviderError(RuntimeError):
    """Base exception for Cloudflare provider failures."""


class CloudflareConfigurationError(CloudflareProviderError):
    """Raised when runtime configuration is incomplete or invalid."""


class CloudflareNetworkError(CloudflareProviderError):
    """Raised when the Cloudflare API cannot be reached."""


class CloudflareAuthenticationError(CloudflareProviderError):
    """Raised when the API token is rejected."""


class CloudflarePermissionError(CloudflareProviderError):
    """Raised when the API token lacks a required permission."""


class CloudflareZoneNotFoundError(CloudflareProviderError):
    """Raised when the configured zone cannot be resolved."""


class CloudflareConflictError(CloudflareProviderError):
    """Raised when DNS record constraints are violated."""


class CloudflareAPIError(CloudflareProviderError):
    """Raised when Cloudflare returns an API-level failure."""


class CloudflareProviderConfig(BaseModel):
    """Cloudflare provider runtime configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    zone_name: str | None
    zone_id: str | None
    api_token_file: str
    timeout_seconds: float = Field(gt=0)
    proxied: bool | None
    ttl: int = Field(ge=1)

    @field_validator("zone_name", "zone_id")
    @classmethod
    def _strip_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("api_token_file")
    @classmethod
    def _validate_api_token_file(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("api_token_file must not be blank")
        return stripped

    @model_validator(mode="after")
    def _validate_zone_locator(self) -> Self:
        if self.zone_id is None and self.zone_name is None:
            raise ValueError("either zone_id or zone_name must be configured for Cloudflare")
        return self

    def resolved_api_token_file(self) -> Path:
        """Return the configured API token path."""

        return Path(self.api_token_file).expanduser()

    def resolved_api_token(self) -> str:
        """Read and strip the configured API token."""

        token_path = self.resolved_api_token_file()
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise CloudflareConfigurationError(
                f"Cloudflare API token file does not exist: {token_path}"
            ) from exc
        except OSError as exc:
            raise CloudflareConfigurationError(
                f"Cloudflare API token file is not readable: {token_path}"
            ) from exc
        if not token:
            raise CloudflareConfigurationError(
                f"Cloudflare API token file is empty: {token_path}"
            )
        return token


class CloudflareDNSProvider(DNSProvider):
    """Cloudflare DNS provider backed by the official v4 REST API."""

    name = "cloudflare"

    def __init__(
        self,
        config: CloudflareProviderConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        if not config.enabled:
            raise CloudflareConfigurationError("Cloudflare provider is disabled in config")
        self._api_token = config.resolved_api_token()
        self._http_client = http_client or httpx.Client()
        self._zone_id_cache = config.zone_id

    def resolve_zone_id(self) -> str:
        """Return the active Cloudflare zone id, resolving by name if needed."""

        if self._zone_id_cache is not None:
            return self._zone_id_cache
        if self._config.zone_name is None:
            raise CloudflareConfigurationError("zone_name is required when zone_id is not set")

        payload = self._request_json(
            "GET",
            "/zones",
            params={"name": self._config.zone_name},
        )
        result = payload.get("result")
        if not isinstance(result, list):
            raise CloudflareAPIError("Cloudflare zones response did not contain a result list")

        matches = [
            zone
            for zone in result
            if isinstance(zone, dict) and zone.get("name") == self._config.zone_name
        ]
        if not matches:
            raise CloudflareZoneNotFoundError(
                f"Cloudflare zone not found for name: {self._config.zone_name}"
            )
        if len(matches) > 1:
            raise CloudflareAPIError(
                f"multiple Cloudflare zones matched name: {self._config.zone_name}"
            )
        zone_id = matches[0].get("id")
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise CloudflareAPIError("Cloudflare zone response did not include a usable id")
        self._zone_id_cache = zone_id
        return zone_id

    def list_records(self, fqdn: str, record_type: str | None = None) -> list[DNSRecord]:
        """List Cloudflare DNS records for a fqdn and optional type."""

        params: dict[str, str] = {"name": fqdn, "per_page": "100"}
        if record_type is not None:
            params["type"] = record_type.upper()
        payload = self._request_json(
            "GET",
            f"/zones/{self.resolve_zone_id()}/dns_records",
            params=params,
        )
        result = payload.get("result")
        if not isinstance(result, list):
            raise CloudflareAPIError("Cloudflare DNS list response did not contain a result list")
        return [self._record_from_api_item(item) for item in result]

    def create_record(self, desired: DesiredRecord) -> DNSRecord:
        """Create a new A or AAAA record."""

        self._ensure_no_cname_conflict(desired.fqdn)
        create_payload: dict[str, object] = {
            "type": desired.record_type,
            "name": desired.fqdn,
            "content": desired.value,
            "ttl": desired.ttl,
        }
        if desired.proxied is not None:
            create_payload["proxied"] = desired.proxied
        payload = self._request_json(
            "POST",
            f"/zones/{self.resolve_zone_id()}/dns_records",
            json_body=create_payload,
        )
        return self._record_from_api_item(payload.get("result"))

    def update_record(self, current: DNSRecord, desired: DesiredRecord) -> DNSRecord:
        """Patch an existing A or AAAA record."""

        record_id = self._resolve_record_id(current)
        patch: dict[str, object] = {}
        if current.value != desired.value:
            patch["content"] = desired.value
        if self._should_manage_ttl(current, desired) and current.ttl != desired.ttl:
            patch["ttl"] = desired.ttl
        if desired.proxied is not None and current.proxied != desired.proxied:
            patch["proxied"] = desired.proxied
        if not patch:
            return current

        payload = self._request_json(
            "PATCH",
            f"/zones/{self.resolve_zone_id()}/dns_records/{record_id}",
            json_body=patch,
        )
        return self._record_from_api_item(payload.get("result"))

    def delete_record(self, current: DNSRecord) -> None:
        """Delete a specific record by id, or resolve the id if needed."""

        record_id = self._resolve_record_id(current)
        self._request_json(
            "DELETE",
            f"/zones/{self.resolve_zone_id()}/dns_records/{record_id}",
        )

    def apply_change(self, change: PlannedChange) -> DNSRecord | None:
        """Apply a planner-produced change against Cloudflare."""

        if change.action == "noop":
            return change.current
        if change.action == "create":
            if change.desired is None:
                raise CloudflareAPIError("create change is missing desired record data")
            return self.create_record(change.desired)
        if change.action == "update":
            if change.current is None or change.desired is None:
                raise CloudflareAPIError("update change requires current and desired records")
            return self.update_record(change.current, change.desired)
        if change.action == "delete":
            if change.current is None:
                raise CloudflareAPIError("delete change requires current record data")
            self.delete_record(change.current)
            return None
        raise CloudflareAPIError(f"unsupported planned change action: {change.action}")

    def verify(self) -> ProviderVerification:
        """Verify token, zone lookup, and DNS listing access."""

        zone_id = self.resolve_zone_id()
        payload = self._request_json(
            "GET",
            f"/zones/{zone_id}/dns_records",
            params={"per_page": "1"},
        )
        result = payload.get("result")
        if not isinstance(result, list):
            raise CloudflareAPIError("Cloudflare DNS list response did not contain a result list")
        return ProviderVerification(
            provider=self.name,
            token_file=str(self._config.resolved_api_token_file()),
            zone_id=zone_id,
            zone_name=self._config.zone_name,
            record_listing_succeeded=True,
        )

    def _resolve_record_id(self, record: DNSRecord) -> str:
        if record.record_id is not None:
            return record.record_id

        matches = self.list_records(record.fqdn, record.record_type)
        exact_matches = [item for item in matches if item.value == record.value]
        if len(exact_matches) != 1:
            raise CloudflareAPIError(
                "unable to determine a unique Cloudflare record id for delete/update"
            )
        if exact_matches[0].record_id is None:
            raise CloudflareAPIError("Cloudflare record lookup did not return a record id")
        return exact_matches[0].record_id

    def _ensure_no_cname_conflict(self, fqdn: str) -> None:
        existing_records = self.list_records(fqdn)
        if any(record.record_type == "CNAME" for record in existing_records):
            raise CloudflareConflictError(
                f"cannot create A/AAAA record for {fqdn} because a CNAME record already exists"
            )

    def _should_manage_ttl(self, current: DNSRecord, desired: DesiredRecord) -> bool:
        return not (desired.proxied is None and current.proxied is True)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        try:
            response = self._http_client.request(
                method,
                f"{API_BASE_URL}{path}",
                headers={
                    "Authorization": f"Bearer {self._api_token}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=json_body,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise CloudflareNetworkError("failed to reach Cloudflare API") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise CloudflareAPIError(
                f"Cloudflare API returned a non-JSON response with status {response.status_code}"
            ) from exc

        if not isinstance(payload, dict):
            raise CloudflareAPIError("Cloudflare API returned an unexpected JSON shape")

        if payload.get("success") is False:
            self._raise_api_error(response, payload)
        if response.is_error:
            raise CloudflareAPIError(
                f"Cloudflare API returned HTTP {response.status_code} without success"
            )
        return payload

    def _raise_api_error(
        self,
        response: httpx.Response,
        payload: dict[str, object],
    ) -> None:
        message = _format_cloudflare_errors(payload)
        if response.status_code == 401:
            raise CloudflareAuthenticationError(message)
        if response.status_code == 403:
            if "auth" in message.lower():
                raise CloudflareAuthenticationError(message)
            raise CloudflarePermissionError(message)
        if "cname" in message.lower():
            raise CloudflareConflictError(message)
        if response.status_code == 404 and "/zones/" in response.request.url.path:
            raise CloudflareZoneNotFoundError(message)
        raise CloudflareAPIError(message)

    def _record_from_api_item(self, item: object) -> DNSRecord:
        if not isinstance(item, dict):
            raise CloudflareAPIError("Cloudflare DNS record item was not an object")
        record_id = item.get("id")
        name = item.get("name")
        record_type = item.get("type")
        content = item.get("content")
        ttl = item.get("ttl")
        proxied = item.get("proxied")
        if (
            not isinstance(name, str)
            or not isinstance(record_type, str)
            or not isinstance(content, str)
        ):
            raise CloudflareAPIError("Cloudflare DNS record item was missing required fields")
        if not isinstance(ttl, int):
            raise CloudflareAPIError("Cloudflare DNS record item did not contain an integer ttl")
        return DNSRecord(
            provider=self.name,
            fqdn=name,
            record_type=record_type,
            value=content,
            ttl=ttl,
            record_id=record_id if isinstance(record_id, str) else None,
            proxied=proxied if isinstance(proxied, bool) else None,
        )


def _format_cloudflare_errors(payload: dict[str, object]) -> str:
    details: list[str] = []
    for key in ("errors", "messages"):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                code = item.get("code")
                message = item.get("message")
                if isinstance(code, int) and isinstance(message, str):
                    details.append(f"{code}: {message}")
                elif isinstance(message, str):
                    details.append(message)
            elif isinstance(item, str):
                details.append(item)
    if not details:
        return "Cloudflare API request failed without a detailed error message"
    return "; ".join(details)
