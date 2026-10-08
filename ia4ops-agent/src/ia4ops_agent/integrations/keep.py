"""Minimal async client for the Keep API; not wired into the incident workflow yet."""

from typing import Any, Literal
from urllib.parse import quote

import httpx

from ia4ops_agent.config import settings

IncidentSeverity = Literal["critical", "high", "warning", "info", "low"]
IncidentActivityStatus = Literal["firing", "resolved", "acknowledged", "merged", "deleted"]


class KeepConfigurationError(ValueError):
    """Required Keep API configuration is missing."""


class KeepAPIError(RuntimeError):
    """Keep API request or response failed."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class KeepClient:
    """Calls selected Keep API endpoints using an API key in X-API-KEY."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise KeepConfigurationError("KEEP_API_BASE_URL is not configured.")
        if not api_key.strip():
            raise KeepConfigurationError("KEEP_API_KEY is not configured.")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    @classmethod
    def from_settings(
        cls,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> KeepClient:
        """Build a client from environment settings without making a request."""
        if not settings.keep_api_base_url:
            raise KeepConfigurationError("KEEP_API_BASE_URL is not configured.")
        if not settings.keep_api_key:
            raise KeepConfigurationError("KEEP_API_KEY is not configured.")
        return cls(
            base_url=settings.keep_api_base_url,
            api_key=settings.keep_api_key,
            transport=transport,
        )

    async def get_alert(self, fingerprint: str) -> dict[str, Any]:
        """Fetch an alert by its Alertmanager fingerprint."""
        if not fingerprint:
            raise ValueError("fingerprint must not be empty")
        result = await self._request_json(
            "GET",
            f"/alerts/{quote(fingerprint, safe='')}",
            expected_type=dict,
        )
        return result

    async def create_incident(
        self,
        *,
        name: str,
        summary: str,
        severity: IncidentSeverity,
    ) -> dict[str, Any]:
        """Create an incident; Keep documents this operation as HTTP 202."""
        if not name.strip():
            raise ValueError("name must not be empty")
        if not summary.strip():
            raise ValueError("summary must not be empty")
        return await self._request_json(
            "POST",
            "/incidents",
            expected_type=dict,
            expected_status=202,
            json={
                "user_generated_name": name,
                "user_summary": summary,
                "severity": severity,
            },
        )

    async def add_alerts_to_incident(
        self,
        incident_id: str,
        fingerprints: list[str],
    ) -> list[dict[str, Any]]:
        """Associate existing Keep alerts with an incident."""
        if not incident_id:
            raise ValueError("incident_id must not be empty")
        if not fingerprints or any(not fingerprint for fingerprint in fingerprints):
            raise ValueError("fingerprints must contain at least one non-empty value")
        result = await self._request_json(
            "POST",
            f"/incidents/{quote(incident_id, safe='')}/alerts",
            expected_type=list,
            expected_status=202,
            json=fingerprints,
        )
        return result

    async def add_comment(
        self,
        incident_id: str,
        *,
        comment: str,
        status: IncidentActivityStatus,
    ) -> dict[str, Any]:
        """Add an incident activity; status is required by Keep's API contract."""
        if not incident_id:
            raise ValueError("incident_id must not be empty")
        if not comment.strip():
            raise ValueError("comment must not be empty")
        return await self._request_json(
            "POST",
            f"/incidents/{quote(incident_id, safe='')}/comment",
            expected_type=dict,
            json={"status": status, "comment": comment},
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        expected_type: type[dict] | type[list],
        expected_status: int = 200,
        json: Any = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(
                headers={"X-API-KEY": self._api_key},
                timeout=15.0,
                transport=self._transport,
            ) as client:
                response = await client.request(method, url, json=json)
                if response.status_code != expected_status:
                    raise KeepAPIError(
                        f"Keep API {method} {path} returned HTTP {response.status_code}; "
                        f"expected {expected_status}.",
                        status_code=response.status_code,
                    )
                payload = response.json()
        except httpx.HTTPError as exc:
            raise KeepAPIError(
                f"Keep API request failed ({method} {path}, {type(exc).__name__})."
            ) from exc
        except ValueError as exc:
            raise KeepAPIError(f"Keep API returned invalid JSON ({method} {path}).") from exc

        if not isinstance(payload, expected_type):
            raise KeepAPIError(
                f"Keep API returned an unexpected JSON type ({method} {path})."
            )
        return payload
