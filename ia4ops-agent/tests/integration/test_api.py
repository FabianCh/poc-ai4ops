"""
Tests d'intégration — API FastAPI (Task 5).

Couverture :
- POST /webhooks/alertmanager : payload v4 valide → 200 accepted immédiat
- POST /webhooks/alertmanager : payload invalide → 422
- POST /webhooks/alertmanager : même fingerprint+startsAt deux fois → duplicate_ignored
- POST /webhooks/alertmanager : alerte Watchdog → accepted (ignoré silencieusement)
- GET  /api/v1/incidents/{id} : après traitement → rapport complet (status completed*)
- GET  /api/v1/incidents/{id} : id inconnu → 404
- GET  /health                : 200 ok

Pattern :
  - app.router.lifespan_context(app) pour déclencher le lifespan dans les tests async
  - httpx.AsyncClient + ASGITransport pour les requêtes HTTP
  - asyncio.sleep pour attendre la BackgroundTask (graphe async en fond)
  - Providers mockés + FakeLLMClient (pas d'appel réseau)
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ia4ops_agent.config import settings
from ia4ops_agent.integrations.keep import KeepAPIError
from ia4ops_agent.main import app

# ---------------------------------------------------------------------------
# Fixture : client HTTP avec lifespan complet
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient]:
    """
    Client ASGI qui démarre et arrête le lifespan FastAPI.

    Utilise app.router.lifespan_context pour déclencher le lifespan
    (app.state.graph, incident_store, dedup_cache sont initialisés).
    """
    monkeypatch.setattr(settings, "keep_api_base_url", None)
    monkeypatch.setattr(settings, "keep_api_key", None)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c


# ---------------------------------------------------------------------------
# Helpers : payloads Alertmanager v4
# ---------------------------------------------------------------------------


def _alert_payload(
    service_name: str,
    fingerprint: str,
    starts_at: str = "2026-10-05T12:00:00Z",
) -> dict[str, Any]:
    return {
        "version": "4",
        "groupKey": "{/}{namespace='otel-demo'}:{alertname='OtelDemoServiceHighErrorRate'}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "ai4ops-agent",
        "groupLabels": {"namespace": "otel-demo"},
        "commonLabels": {
            "namespace": "otel-demo",
            "alertname": "OtelDemoServiceHighErrorRate",
        },
        "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "OtelDemoServiceHighErrorRate",
                    "namespace": "otel-demo",
                    "severity": "critical",
                    "service_name": service_name,
                },
                "annotations": {"summary": f"High error rate on {service_name}"},
                "startsAt": starts_at,
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus/graph",
                "fingerprint": fingerprint,
            }
        ],
    }


def _watchdog_payload() -> dict[str, Any]:
    return {
        "version": "4",
        "groupKey": "{/}{alertname='Watchdog'}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "ai4ops-agent",
        "groupLabels": {},
        "commonLabels": {"alertname": "Watchdog"},
        "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "Watchdog", "namespace": "monitoring"},
                "annotations": {"summary": "Alertmanager heartbeat"},
                "startsAt": "2026-10-05T12:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "",
                "fingerprint": "watchdog-fp-001",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Helper : attendre la fin du traitement
# ---------------------------------------------------------------------------


async def _wait_for_completion(
    client: AsyncClient,
    incident_id: str,
    timeout: float = 10.0,
) -> dict:
    """
    Poll GET /api/v1/incidents/{id} jusqu'à ce que le status soit terminal.
    Lève AssertionError si le timeout est dépassé.
    """
    terminal_statuses = {"completed", "completed_with_errors", "failed"}
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        resp = await client.get(f"/api/v1/incidents/{incident_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in terminal_statuses:
            return data
        await asyncio.sleep(0.05)
    raise AssertionError(f"Incident {incident_id!r} pas terminé après {timeout}s")


# ---------------------------------------------------------------------------
# Tests : POST /webhooks/alertmanager
# ---------------------------------------------------------------------------


async def test_webhook_valid_payload_returns_accepted(client: AsyncClient) -> None:
    """Un payload v4 valide doit retourner 200 avec status 'accepted'."""
    payload = _alert_payload("product-catalog", "test-fp-001")
    resp = await client.post("/webhooks/alertmanager", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert "incident_id" in data
    assert data["incident_id"]  # non vide


async def test_webhook_invalid_payload_returns_422(client: AsyncClient) -> None:
    """Un payload sans champ obligatoire doit retourner 422."""
    bad_payload = {"version": "4", "status": "firing"}  # manque alerts, receiver, etc.
    resp = await client.post("/webhooks/alertmanager", json=bad_payload)
    assert resp.status_code == 422


async def test_webhook_wrong_version_returns_422(client: AsyncClient) -> None:
    """Un payload avec version != '4' doit être rejeté."""
    payload = _alert_payload("product-catalog", "test-fp-v3")
    payload["version"] = "3"
    resp = await client.post("/webhooks/alertmanager", json=payload)
    assert resp.status_code == 422


async def test_webhook_empty_alerts_returns_422(client: AsyncClient) -> None:
    """Un payload avec alerts vide doit être rejeté (model_validator)."""
    payload = _alert_payload("product-catalog", "test-fp-empty")
    payload["alerts"] = []
    resp = await client.post("/webhooks/alertmanager", json=payload)
    assert resp.status_code == 422


async def test_webhook_duplicate_returns_duplicate_ignored(client: AsyncClient) -> None:
    """
    Deux notifications avec le même fingerprint+startsAt → le second reçoit
    'duplicate_ignored'. Alertmanager ne doit pas réessayer.
    """
    payload = _alert_payload("product-catalog", "test-fp-dup", "2026-10-05T13:00:00Z")

    resp1 = await client.post("/webhooks/alertmanager", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "accepted"

    resp2 = await client.post("/webhooks/alertmanager", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate_ignored"


async def test_webhook_different_startsAt_not_duplicate(client: AsyncClient) -> None:
    """Même fingerprint mais startsAt différent → deux incidents distincts."""
    payload1 = _alert_payload("checkout", "test-fp-ts1", "2026-10-05T14:00:00Z")
    payload2 = _alert_payload("checkout", "test-fp-ts1", "2026-10-05T15:00:00Z")

    resp1 = await client.post("/webhooks/alertmanager", json=payload1)
    resp2 = await client.post("/webhooks/alertmanager", json=payload2)

    assert resp1.json()["status"] == "accepted"
    assert resp2.json()["status"] == "accepted"
    # Les deux incidents doivent avoir des IDs distincts
    assert resp1.json()["incident_id"] != resp2.json()["incident_id"]


async def test_webhook_resolved_updates_existing_incident_without_rerunning(
    client: AsyncClient,
) -> None:
    """Une résolution met à jour l'incident existant sans lancer un second graphe."""
    payload = _alert_payload("product-catalog", "test-fp-resolved")
    firing_response = await client.post("/webhooks/alertmanager", json=payload)
    incident_id = firing_response.json()["incident_id"]
    completed = await _wait_for_completion(client, incident_id)

    resolved_payload = {
        **payload,
        "status": "resolved",
        "alerts": [
            {
                **payload["alerts"][0],
                "status": "resolved",
                "endsAt": "2026-10-05T12:10:00Z",
            }
        ],
    }
    resolved_response = await client.post(
        "/webhooks/alertmanager",
        json=resolved_payload,
    )

    assert resolved_response.status_code == 200
    assert resolved_response.json()["status"] == "resolved"
    assert resolved_response.json()["incident_id"] == incident_id

    incident_response = await client.get(f"/api/v1/incidents/{incident_id}")
    incident = incident_response.json()
    assert incident["status"] == completed["status"]
    assert incident["report"] == completed["report"]
    assert incident["alert_status"] == "resolved"
    assert incident["resolved_at"] == "2026-10-05T12:10:00+00:00"


async def test_webhook_unmatched_resolved_is_acknowledged_without_diagnosis(
    client: AsyncClient,
) -> None:
    """Une résolution orpheline est acquittée et ne crée pas de nouvel incident."""
    payload = _alert_payload("product-catalog", "test-fp-orphan-resolved")
    payload["status"] = "resolved"
    payload["alerts"][0]["status"] = "resolved"
    payload["alerts"][0]["endsAt"] = "2026-10-05T12:10:00Z"

    response = await client.post("/webhooks/alertmanager", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "resolved_unmatched"
    assert response.json()["incident_id"] is None
    assert not app.state.incident_store


async def test_webhook_watchdog_returns_accepted(client: AsyncClient) -> None:
    """L'alerte Watchdog est acceptée silencieusement (pas de diagnostic lancé)."""
    resp = await client.post("/webhooks/alertmanager", json=_watchdog_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["incident_id"] == "watchdog"


# ---------------------------------------------------------------------------
# Tests : GET /api/v1/incidents/{incident_id}
# ---------------------------------------------------------------------------


async def test_get_incident_unknown_returns_404(client: AsyncClient) -> None:
    """Un incident_id inconnu doit retourner 404."""
    resp = await client.get("/api/v1/incidents/inc-unknown-0000")
    assert resp.status_code == 404


async def test_get_incident_registered_after_post(client: AsyncClient) -> None:
    """
    Immédiatement après le POST, l'incident est dans le store
    (pending, running ou déjà complété selon la vitesse du graphe).
    """
    payload = _alert_payload("checkout", "test-fp-pending", "2026-10-05T16:00:00Z")
    resp = await client.post("/webhooks/alertmanager", json=payload)
    assert resp.status_code == 200
    incident_id = resp.json()["incident_id"]

    get_resp = await client.get(f"/api/v1/incidents/{incident_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["status"] in {"pending", "running", "completed", "completed_with_errors"}


async def test_get_incident_case_a_completes_with_diagnosis(client: AsyncClient) -> None:
    """
    Cas A (product-catalog) : le graphe doit se terminer avec un rapport
    contenant un diagnostic non vide et action_executed=False.
    """
    payload = _alert_payload("product-catalog", "test-fp-case-a", "2026-10-05T17:00:00Z")
    resp = await client.post("/webhooks/alertmanager", json=payload)
    assert resp.status_code == 200
    incident_id = resp.json()["incident_id"]

    data = await _wait_for_completion(client, incident_id)
    assert data["status"] in {"completed", "completed_with_errors"}

    report = data["report"]
    assert report is not None
    assert report["action_executed"] is False

    diagnosis = report.get("diagnosis", {})
    assert report["incident_id"] == incident_id
    assert diagnosis.get("affected_service") == "product-catalog"
    assert diagnosis.get("severity_assessment") == "critical"
    assert diagnosis.get("action_executed") is False


async def test_get_incident_case_b_completes_with_diagnosis(client: AsyncClient) -> None:
    """
    Cas B (checkout) : OOMKilled — diagnostic doit mentionner checkout.
    """
    payload = _alert_payload("checkout", "test-fp-case-b", "2026-10-05T18:00:00Z")
    resp = await client.post("/webhooks/alertmanager", json=payload)
    assert resp.status_code == 200
    incident_id = resp.json()["incident_id"]

    data = await _wait_for_completion(client, incident_id)
    report = data["report"]
    diagnosis = report.get("diagnosis", {})
    assert diagnosis.get("affected_service") == "checkout"
    assert diagnosis.get("action_executed") is False


async def test_get_incident_case_c_unknown_severity(client: AsyncClient) -> None:
    """
    Cas C (frontend) : données insuffisantes — severity_assessment='unknown',
    missing_information non vide.
    """
    payload = _alert_payload("frontend", "test-fp-case-c", "2026-10-05T19:00:00Z")
    resp = await client.post("/webhooks/alertmanager", json=payload)
    assert resp.status_code == 200
    incident_id = resp.json()["incident_id"]

    data = await _wait_for_completion(client, incident_id)
    report = data["report"]
    diagnosis = report.get("diagnosis", {})
    assert diagnosis.get("severity_assessment") == "unknown"
    assert len(report.get("missing_information", [])) > 0


async def test_report_always_has_action_executed_false(client: AsyncClient) -> None:
    """
    Invariant scénario 1 : quel que soit le cas, action_executed doit être False
    dans le rapport final ET dans le diagnostic.
    """
    cases = [
        ("product-catalog", "test-fp-inv-a", "2026-10-05T20:00:00Z"),
        ("checkout", "test-fp-inv-b", "2026-10-05T20:01:00Z"),
        ("frontend", "test-fp-inv-c", "2026-10-05T20:02:00Z"),
    ]
    for service, fp, starts in cases:
        payload = _alert_payload(service, fp, starts)
        resp = await client.post("/webhooks/alertmanager", json=payload)
        incident_id = resp.json()["incident_id"]
        data = await _wait_for_completion(client, incident_id)

        assert data["report"]["action_executed"] is False, (
            f"action_executed True dans le rapport pour {service}"
        )
        diagnosis = data["report"].get("diagnosis", {})
        assert diagnosis.get("action_executed") is False, (
            f"diagnosis.action_executed True pour {service}"
        )


async def test_completed_diagnosis_is_sent_to_keep(client: AsyncClient) -> None:
    """A completed report is published once through the configured Keep publisher."""
    calls: list[dict[str, Any]] = []

    class RecordingPublisher:
        async def publish_diagnosis(self, **kwargs: Any) -> str:
            calls.append(kwargs)
            return "keep-incident-1"

    app.state.keep_publisher = RecordingPublisher()
    payload = _alert_payload("product-catalog", "test-fp-keep-publish")

    response = await client.post("/webhooks/alertmanager", json=payload)
    incident_id = response.json()["incident_id"]
    await _wait_for_completion(client, incident_id)

    assert len(calls) == 1
    assert calls[0]["agent_incident_id"] == incident_id
    assert calls[0]["payload"]["alerts"][0]["fingerprint"] == "test-fp-keep-publish"
    assert calls[0]["alert_status"] == "firing"
    assert calls[0]["report"]["action_executed"] is False


async def test_keep_failure_does_not_fail_local_diagnosis(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A Keep API error is visible in logs but does not change the local report status."""

    class FailingPublisher:
        async def publish_diagnosis(self, **kwargs: Any) -> str:
            raise KeepAPIError("Keep API returned HTTP 403.", status_code=403)

    app.state.keep_publisher = FailingPublisher()
    response = await client.post(
        "/webhooks/alertmanager",
        json=_alert_payload("product-catalog", "test-fp-keep-failure"),
    )
    incident_id = response.json()["incident_id"]

    result = await _wait_for_completion(client, incident_id)

    assert result["status"] in {"completed", "completed_with_errors"}
    assert "Échec publication Keep (diagnosis)" in caplog.text


async def test_repeated_resolved_webhooks_use_the_same_keep_idempotency_key(
    client: AsyncClient,
) -> None:
    """A matched resolution carries a stable key so KeepPublisher can suppress repeats."""
    calls: list[dict[str, Any]] = []

    class RecordingPublisher:
        async def publish_diagnosis(self, **kwargs: Any) -> str:
            return "keep-incident-1"

        async def publish_resolution(self, **kwargs: Any) -> list[str]:
            calls.append(kwargs)
            return ["keep-incident-1"]

    app.state.keep_publisher = RecordingPublisher()
    payload = _alert_payload("product-catalog", "test-fp-keep-resolved")
    firing_response = await client.post("/webhooks/alertmanager", json=payload)
    incident_id = firing_response.json()["incident_id"]
    await _wait_for_completion(client, incident_id)
    resolved_payload = {
        **payload,
        "status": "resolved",
        "alerts": [
            {
                **payload["alerts"][0],
                "status": "resolved",
                "endsAt": "2026-10-08T10:00:00Z",
            }
        ],
    }

    first = await client.post("/webhooks/alertmanager", json=resolved_payload)
    repeated = await client.post("/webhooks/alertmanager", json=resolved_payload)

    assert first.json()["status"] == "resolved"
    assert repeated.json()["status"] == "resolved"
    assert len(calls) == 2
    assert calls[0]["dedup_key"] == calls[1]["dedup_key"]
    assert calls[0]["resolved_at"] == "2026-10-08T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Tests : GET /health
# ---------------------------------------------------------------------------


async def test_health_returns_200(client: AsyncClient) -> None:
    """Le health check doit toujours retourner 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
