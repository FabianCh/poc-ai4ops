"""Contract tests for the Keep API client using simulated HTTP responses."""

import json

import httpx
import pytest

from ia4ops_agent.config import settings
from ia4ops_agent.integrations.keep import (
    KeepAPIError,
    KeepClient,
    KeepConfigurationError,
)


def _client(transport: httpx.AsyncBaseTransport) -> KeepClient:
    return KeepClient(
        base_url="https://keep.example.test/v2/",
        api_key="test-api-key",
        transport=transport,
    )


async def test_get_alert_uses_fingerprint_route_and_api_key_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == "https://keep.example.test/v2/alerts/fp-123"
        assert request.headers["X-API-KEY"] == "test-api-key"
        return httpx.Response(
            200,
            json={"fingerprint": "fp-123", "incident": ""},
            request=request,
        )

    alert = await _client(httpx.MockTransport(handler)).get_alert("fp-123")

    assert alert == {"fingerprint": "fp-123", "incident": ""}


async def test_create_incident_sends_documented_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v2/incidents"
        assert json.loads(request.content) == {
            "user_generated_name": "IA4Ops: test alert",
            "user_summary": "Test summary",
            "severity": "critical",
        }
        return httpx.Response(202, json={"id": "incident-123"}, request=request)

    incident = await _client(httpx.MockTransport(handler)).create_incident(
        name="IA4Ops: test alert",
        summary="Test summary",
        severity="critical",
    )

    assert incident["id"] == "incident-123"


async def test_add_alerts_accepts_empty_202_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v2/incidents/incident-123/alerts"
        assert json.loads(request.content) == ["fp-123", "fp-456"]
        return httpx.Response(202, content=b"", request=request)

    result = await _client(httpx.MockTransport(handler)).add_alerts_to_incident(
        "incident-123",
        ["fp-123", "fp-456"],
    )

    assert result is None


async def test_add_comment_includes_required_status_and_comment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v2/incidents/incident-123/comment"
        assert json.loads(request.content) == {
            "status": "firing",
            "comment": "Diagnostic de test.",
        }
        return httpx.Response(
            200,
            json={"fingerprint": "fp-123", "action": "comment"},
            request=request,
        )

    activity = await _client(httpx.MockTransport(handler)).add_comment(
        "incident-123",
        comment="Diagnostic de test.",
        status="firing",
    )

    assert activity["action"] == "comment"


async def test_api_error_does_not_include_api_key() -> None:
    client = _client(
        httpx.MockTransport(
            lambda request: httpx.Response(403, json={"detail": "forbidden"}, request=request)
        )
    )

    with pytest.raises(KeepAPIError, match="HTTP 403") as error:
        await client.get_alert("fp-123")

    assert "test-api-key" not in str(error.value)
    assert error.value.status_code == 403


async def test_unexpected_response_shape_is_reported() -> None:
    client = _client(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=[], request=request)
        )
    )

    with pytest.raises(KeepAPIError, match="unexpected JSON type"):
        await client.get_alert("fp-123")


def test_from_settings_requires_url_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "keep_api_base_url", None)
    monkeypatch.setattr(settings, "keep_api_key", None)

    with pytest.raises(KeepConfigurationError, match="KEEP_API_BASE_URL"):
        KeepClient.from_settings()


@pytest.mark.parametrize(
    ("method", "args", "kwargs"),
    [
        ("get_alert", ("",), {}),
        ("create_incident", (), {"name": "", "summary": "summary", "severity": "info"}),
        ("add_alerts_to_incident", ("incident", []), {}),
        (
            "add_comment",
            ("incident",),
            {"comment": "   ", "status": "firing"},
        ),
    ],
)
async def test_invalid_inputs_fail_before_network_request(
    method: str,
    args: tuple,
    kwargs: dict,
) -> None:
    def unexpected_request(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected request: {request.method} {request.url}")

    client = _client(httpx.MockTransport(unexpected_request))
    with pytest.raises(ValueError):
        await getattr(client, method)(*args, **kwargs)
