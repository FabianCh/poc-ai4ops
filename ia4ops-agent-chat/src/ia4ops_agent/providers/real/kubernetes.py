"""
Provider Kubernetes réel — lecture seule de l'API in-cluster.

Accès : jeton du ServiceAccount monté dans le pod (`ia4ops-agent`), CA du cluster.
RBAC  : Role `get`/`list` sur pods, events, deployments et replicasets du seul namespace
        `otel-demo` (voir manifest/applications/ia4ops-agent/). Aucune écriture, aucun
        secret, aucun log de pod.

Les événements et les noms de pods sont du contenu externe non fiable : seuls des champs
d'une liste blanche sont copiés (aucune annotation, variable d'environnement ni spec de pod),
les textes sont normalisés puis tronqués, et les listes sont bornées.
"""

import re
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ia4ops_agent.config import settings
from ia4ops_agent.providers.interfaces import ClusterUnavailableError

_API_URL = "https://kubernetes.default.svc"
_SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
_DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
_SELECTOR_PART = re.compile(r"^[A-Za-z0-9._/-]{1,63}$")
_MAX_PODS = 20
_MAX_EVENTS = 20
_MAX_EVENTS_FETCHED = 500
_MAX_TEXT_LENGTH = 200
_MAX_NAME_LENGTH = 100
_TIMEOUT_SECONDS = 5.0


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _allowed_namespaces() -> set[str]:
    return {item.strip() for item in settings.kubernetes_namespaces.split(",") if item.strip()}


def _validate(namespace: str, service: str) -> None:
    if namespace not in _allowed_namespaces():
        raise ClusterUnavailableError(
            f"Namespace {namespace!r} hors de la liste autorisée (KUBERNETES_NAMESPACES)."
        )
    if not _DNS_LABEL.fullmatch(service):
        raise ClusterUnavailableError("Nom de service invalide pour une requête Kubernetes.")


def _label_selector(deployment: dict[str, Any] | None, service: str) -> str:
    """Sélecteur lu sur le Deployment ; repli sur le label standard du service."""
    match_labels = ((deployment or {}).get("spec") or {}).get("selector", {}).get("matchLabels")
    if isinstance(match_labels, dict) and match_labels:
        parts = []
        for key, value in match_labels.items():
            if not (
                isinstance(key, str)
                and isinstance(value, str)
                and _SELECTOR_PART.fullmatch(key)
                and _SELECTOR_PART.fullmatch(value)
            ):
                break
            parts.append(f"{key}={value}")
        else:
            return ",".join(sorted(parts))
    return f"app.kubernetes.io/name={service}"


def _summarize_pod(pod: dict[str, Any]) -> dict[str, Any]:
    status = pod.get("status") or {}
    ready = any(
        isinstance(cond, dict) and cond.get("type") == "Ready" and cond.get("status") == "True"
        for cond in status.get("conditions") or []
    )
    restarts = 0
    waiting_reason: str | None = None
    terminated_reason: str | None = None
    for container in status.get("containerStatuses") or []:
        if not isinstance(container, dict):
            continue
        restarts += _int(container.get("restartCount"))
        waiting = (container.get("state") or {}).get("waiting") or {}
        waiting_reason = waiting_reason or _text(waiting.get("reason"), 60)
        last = (container.get("lastState") or {}).get("terminated") or {}
        terminated_reason = terminated_reason or _text(last.get("reason"), 60)
    summary: dict[str, Any] = {
        "name": _text((pod.get("metadata") or {}).get("name"), _MAX_NAME_LENGTH),
        "phase": _text(status.get("phase"), 30),
        "ready": ready,
        "restarts": restarts,
    }
    if waiting_reason:
        summary["waiting_reason"] = waiting_reason
    if terminated_reason:
        summary["last_terminated_reason"] = terminated_reason
    return summary


def _event_time(event: dict[str, Any]) -> datetime | None:
    for key in ("lastTimestamp", "eventTime", "firstTimestamp"):
        parsed = _parse_time(event.get(key))
        if parsed:
            return parsed
    return _parse_time((event.get("metadata") or {}).get("creationTimestamp"))


class KubernetesProvider:
    """Implémentation réelle de ClusterProvider via l'API Kubernetes (lecture seule)."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        api_url: str = _API_URL,
        service_account_dir: Path = _SERVICE_ACCOUNT_DIR,
    ) -> None:
        self._transport = transport
        self._api_url = api_url.rstrip("/")
        self._sa_dir = service_account_dir

    def _client(self) -> httpx.AsyncClient:
        try:
            token = (self._sa_dir / "token").read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ClusterUnavailableError(
                "Jeton de ServiceAccount absent : l'API Kubernetes n'est pas accessible."
            ) from exc
        if not token:
            raise ClusterUnavailableError("Jeton de ServiceAccount vide.")
        ca_file = self._sa_dir / "ca.crt"
        verify: ssl.SSLContext | bool = True
        if self._transport is None and ca_file.exists():
            verify = ssl.create_default_context(cafile=str(ca_file))
        return httpx.AsyncClient(
            base_url=self._api_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=_TIMEOUT_SECONDS,
            transport=self._transport,
            verify=verify,
        )

    @staticmethod
    async def _get(
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, str] | None = None,
        *,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        try:
            response = await client.get(path, params=params)
            if allow_not_found and response.status_code == 404:
                return None
            if response.status_code in (401, 403):
                raise ClusterUnavailableError(
                    f"Accès refusé par l'API Kubernetes (HTTP {response.status_code}) : RBAC."
                )
            response.raise_for_status()
            payload = response.json()
        except ClusterUnavailableError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ClusterUnavailableError(
                f"Échec de la requête Kubernetes ({type(exc).__name__})."
            ) from exc
        if not isinstance(payload, dict):
            raise ClusterUnavailableError("Réponse Kubernetes invalide.")
        return payload

    async def get_workload_status(
        self,
        service: str,
        namespace: str,
    ) -> dict[str, Any]:
        _validate(namespace, service)
        async with self._client() as client:
            deployment = await self._get(
                client,
                f"/apis/apps/v1/namespaces/{namespace}/deployments/{service}",
                allow_not_found=True,
            )
            pods_payload = await self._get(
                client,
                f"/api/v1/namespaces/{namespace}/pods",
                {"labelSelector": _label_selector(deployment, service)},
            )

        items = (pods_payload or {}).get("items") or []
        pods = [_summarize_pod(pod) for pod in items if isinstance(pod, dict)]
        if deployment is None and not pods:
            raise ClusterUnavailableError(
                f"Aucun deployment ni pod trouvé pour {service!r} dans {namespace!r}."
            )
        # Pods non-ready d'abord : ce sont eux qui expliquent l'incident
        pods.sort(key=lambda pod: (pod["ready"], pod["name"] or ""))

        result: dict[str, Any] = {
            "restart_count": sum(pod["restarts"] for pod in pods),
            "pod_statuses": pods[:_MAX_PODS],
            "status": "success" if deployment is not None else "partial",
        }
        if deployment is not None:
            spec = deployment.get("spec") or {}
            status = deployment.get("status") or {}
            result["desired_replicas"] = _int(spec.get("replicas"))
            result["ready_replicas"] = _int(status.get("readyReplicas"))
        return result

    async def get_cluster_events(
        self,
        namespace: str,
        service: str,
        window_minutes: int = 15,
    ) -> list[dict[str, Any]]:
        _validate(namespace, service)
        if window_minutes < 1:
            raise ValueError("window_minutes doit être supérieur ou égal à 1")
        async with self._client() as client:
            payload = await self._get(
                client,
                f"/api/v1/namespaces/{namespace}/events",
                {"limit": str(_MAX_EVENTS_FETCHED)},
            )

        # nom du service, de son ReplicaSet (hash) ou de son pod (hash + suffixe) : l'ancrage
        # évite de confondre `frontend` avec `frontend-proxy`
        owned = re.compile(rf"^{re.escape(service)}(-[a-z0-9]{{6,10}}(-[a-z0-9]{{5}})?)?$")
        cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
        selected: list[tuple[datetime, dict[str, Any]]] = []
        for event in (payload or {}).get("items") or []:
            if not isinstance(event, dict) or event.get("type") != "Warning":
                continue
            involved = event.get("involvedObject") or {}
            name = involved.get("name")
            when = _event_time(event)
            if not isinstance(name, str) or not owned.fullmatch(name) or when is None:
                continue
            if when < cutoff:
                continue
            kind = _text(involved.get("kind"), 30) or "object"
            selected.append(
                (
                    when,
                    {
                        "type": "Warning",
                        "reason": _text(event.get("reason"), 60),
                        "message": _text(event.get("message"), _MAX_TEXT_LENGTH),
                        "timestamp": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "object": f"{kind.lower()}/{_text(name, _MAX_NAME_LENGTH)}",
                        "count": _int(event.get("count")) or 1,
                    },
                )
            )
        selected.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in selected[:_MAX_EVENTS]]
