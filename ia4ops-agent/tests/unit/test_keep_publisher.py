"""Tests for Keep incident publication and Alertmanager lifecycle updates."""

import json
from typing import Any

import httpx
import pytest

from ia4ops_agent.integrations.keep import KeepAPIError, KeepClient
from ia4ops_agent.integrations.keep_publisher import KeepPublisher


def _payload(*fingerprints: str) -> dict[str, Any]:
    return {
        "alerts": [
            {
                "fingerprint": fingerprint,
                "labels": {
                    "alertname": "HighErrorRate",
                    "service_name": "product-catalog",
                    "severity": "critical",
                },
            }
            for fingerprint in fingerprints
        ]
    }


def _report() -> dict[str, Any]:
    return {
        "diagnosis": {
            "affected_service": "product-catalog",
            "summary": "Elevated request errors.",
            "severity_assessment": "critical",
            "primary_hypothesis": {"title": "Dependency timeout"},
        },
        "source_status": {"metrics": "success", "logs": "partial"},
        "action_executed": False,
    }


async def test_publishes_diagnosis_and_all_alerts_to_one_keep_incident() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"incident": ""}, request=request)
        if request.url.path == "/incidents":
            assert json.loads(request.content) == {
                "user_generated_name": "IA4Ops product-catalog agent-inc-1",
                "user_summary": "Elevated request errors.",
                "severity": "critical",
            }
            return httpx.Response(202, json={"id": "keep-1"}, request=request)
        if request.url.path == "/incidents/keep-1/alerts":
            assert json.loads(request.content) == ["fp-a", "fp-b"]
            return httpx.Response(202, content=b"", request=request)
        if request.url.path == "/incidents/keep-1/comment":
            body = json.loads(request.content)
            assert body["status"] == "firing"
            comments = [
                json.loads(item.content)["comment"]
                for item in requests
                if item.url.path == "/incidents/keep-1/comment"
            ]
            assert len(comments) <= 3
            return httpx.Response(200, json={"action": "comment"}, request=request)
        pytest.fail(f"Unexpected request: {request.method} {request.url}")

    publisher = KeepPublisher(
        KeepClient(
            base_url="http://keep-backend:8080",
            api_key="test-key",
            transport=httpx.MockTransport(handler),
        )
    )

    keep_id = await publisher.publish_diagnosis(
        agent_incident_id="agent-inc-1",
        payload=_payload("fp-a", "fp-b"),
        report=_report(),
    )

    assert keep_id == "keep-1"
    assert sum(request.url.path == "/incidents" for request in requests) == 1
    comments = [
        json.loads(request.content)["comment"]
        for request in requests
        if request.url.path == "/incidents/keep-1/comment"
    ]
    assert len(comments) == 3
    assert "Résumé du diagnostic" in comments[0]
    assert "Elevated request errors." in comments[0]
    assert "Hypothèse principale" in comments[1]
    assert "Dependency timeout" in comments[1]
    assert "Limites et prochaines étapes" in comments[2]
    assert "Aucune action de remédiation n'a été exécutée." in comments[2]


async def test_failed_diagnosis_publishes_clear_failure_activity() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"incident": ""}, request=request)
        if request.url.path == "/incidents":
            body = json.loads(request.content)
            assert body["user_generated_name"] == "IA4Ops product-catalog agent-inc-1"
            assert body["user_summary"] == "IA4Ops diagnostic unavailable"
            return httpx.Response(202, json={"id": "keep-failure"}, request=request)
        if request.url.path.endswith("/alerts"):
            return httpx.Response(202, content=b"", request=request)
        if request.url.path == "/incidents/keep-failure/comment":
            return httpx.Response(200, json={"action": "comment"}, request=request)
        pytest.fail(f"Unexpected request: {request.method} {request.url}")

    publisher = KeepPublisher(
        KeepClient(
            base_url="http://keep-backend:8080",
            api_key="test-key",
            transport=httpx.MockTransport(handler),
        )
    )
    report = {
        "diagnosis": {
            "failure_reason": "Échec de validation Pydantic après 3 tentatives.",
            "attempts": 3,
            "action_executed": False,
        },
        "source_status": {"metrics": "success", "logs": "success", "cluster": "unavailable"},
    }

    await publisher.publish_diagnosis(
        agent_incident_id="agent-inc-1",
        payload=_payload("fp-a"),
        report=report,
    )

    comments = [
        json.loads(request.content)["comment"]
        for request in requests
        if request.url.path == "/incidents/keep-failure/comment"
    ]
    assert len(comments) == 1
    assert "Diagnostic indisponible" in comments[0]
    assert "3 tentative(s)" in comments[0]
    assert "Échec de validation Pydantic" in comments[0]
    assert "Kubernetes : unavailable" in comments[0]
    assert "Aucune hypothèse fiable n'est publiée." in comments[0]
    assert "Résumé du diagnostic" not in comments[0]
    assert "Hypothèse principale" not in comments[0]


def test_diagnosis_comments_include_evidence_and_next_checks() -> None:
    from ia4ops_agent.integrations.keep_publisher import _diagnosis_comments

    diagnosis = {
        **_report()["diagnosis"],
        "primary_hypothesis": {
            "title": "Taux d'erreurs élevé",
            "likelihood": "high",
            "reasoning": "Les erreurs dépassent le seuil observé.",
        },
        "evidence": [
            {
                "source": "metrics",
                "reference": "metrics-error_rate",
                "observation": "Taux d'erreur mesuré à 2.93%.",
            },
            {
                "source": "logs",
                "reference": "logs-errors",
                "observation": "Aucun log ERROR/WARN trouvé.",
            },
        ],
        "missing_information": ["L'état des workloads Kubernetes n'est pas collecté."],
        "recommended_next_checks": ["Vérifier les traces en erreur dans Jaeger."],
    }

    comments = _diagnosis_comments(
        agent_incident_id="agent-inc-1",
        diagnosis=diagnosis,
        source_status={"metrics": "success", "logs": "success", "cluster": "unavailable"},
        alert_status="firing",
        resolved_at=None,
    )

    assert len(comments) == 3
    assert "Hypothèse principale : Taux d'erreurs élevé" in comments[1]
    assert "Les erreurs dépassent le seuil observé." in comments[1]
    assert "- metrics : Taux d'erreur mesuré à 2.93%." in comments[1]
    assert "Aucun log ERROR/WARN trouvé." in comments[1]
    assert "Vérifier les traces en erreur dans Jaeger." in comments[2]
    assert "Kubernetes : unavailable" in comments[2]


async def test_new_alert_in_later_group_reuses_keep_incident() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"incident": ""}, request=request)
        if request.url.path == "/incidents":
            return httpx.Response(202, json={"id": "keep-1"}, request=request)
        if request.url.path.endswith("/alerts"):
            return httpx.Response(202, json=[], request=request)
        return httpx.Response(200, json={"action": "comment"}, request=request)

    publisher = KeepPublisher(
        KeepClient(
            base_url="http://keep-backend:8080",
            api_key="test-key",
            transport=httpx.MockTransport(handler),
        )
    )
    await publisher.publish_diagnosis(
        agent_incident_id="agent-inc-1",
        payload=_payload("fp-a"),
        report=_report(),
    )
    await publisher.publish_diagnosis(
        agent_incident_id="agent-inc-2",
        payload=_payload("fp-a", "fp-late"),
        report=_report(),
    )

    assert sum(request.url.path == "/incidents" for request in requests) == 1
    association_requests = [
        json.loads(request.content)
        for request in requests
        if request.url.path.endswith("/alerts")
    ]
    assert association_requests == [["fp-a"], ["fp-late"]]


async def test_existing_keep_incident_is_reused_for_grouped_alerts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            incident_id = "keep-existing" if request.url.path.endswith("fp-a") else ""
            return httpx.Response(200, json={"incident": incident_id}, request=request)
        if request.url.path.endswith("/alerts"):
            assert json.loads(request.content) == ["fp-b"]
            return httpx.Response(202, json=[], request=request)
        return httpx.Response(200, json={"action": "comment"}, request=request)

    publisher = KeepPublisher(
        KeepClient(
            base_url="http://keep-backend:8080",
            api_key="test-key",
            transport=httpx.MockTransport(handler),
        )
    )
    keep_id = await publisher.publish_diagnosis(
        agent_incident_id="agent-inc-1",
        payload=_payload("fp-a", "fp-b"),
        report=_report(),
    )

    assert keep_id == "keep-existing"
    assert not any(request.url.path == "/incidents" for request in requests)


async def test_rejects_grouped_alerts_already_linked_to_different_incidents() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        incident_id = "keep-a" if request.url.path.endswith("fp-a") else "keep-b"
        return httpx.Response(200, json={"incident": incident_id}, request=request)

    publisher = KeepPublisher(
        KeepClient(
            base_url="http://keep-backend:8080",
            api_key="test-key",
            transport=httpx.MockTransport(handler),
        )
    )

    with pytest.raises(KeepAPIError, match="different Keep incidents"):
        await publisher.publish_diagnosis(
            agent_incident_id="agent-inc-1",
            payload=_payload("fp-a", "fp-b"),
            report=_report(),
        )


async def test_resolution_is_published_once_and_does_not_create_an_incident() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"incident": "keep-existing"}, request=request)
        assert request.url.path == "/incidents/keep-existing/comment"
        assert json.loads(request.content)["status"] == "resolved"
        return httpx.Response(200, json={"action": "comment"}, request=request)

    publisher = KeepPublisher(
        KeepClient(
            base_url="http://keep-backend:8080",
            api_key="test-key",
            transport=httpx.MockTransport(handler),
        )
    )
    published = await publisher.publish_resolution(
        dedup_key="group:starts",
        fingerprints=["fp-a"],
        resolved_at="2026-10-08T10:00:00+00:00",
    )
    repeated = await publisher.publish_resolution(
        dedup_key="group:starts",
        fingerprints=["fp-a"],
        resolved_at="2026-10-08T10:00:00+00:00",
    )

    assert published == ["keep-existing"]
    assert repeated == []
    assert sum(request.method == "POST" for request in requests) == 1
