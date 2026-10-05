"""
AuditWriter — écriture append-only de l'audit trail en JSON Lines.

Chaque AuditEvent est écrit sur une ligne. Le fichier est nommé par incident_id
pour faciliter la corrélation. En cas d'erreur d'écriture, on log l'erreur sans
planter le workflow (l'audit ne doit pas bloquer le diagnostic).
"""

import logging
from pathlib import Path

from ia4ops_agent.audit.models import AuditEvent

logger = logging.getLogger(__name__)

DEFAULT_AUDIT_DIR = Path("audit_logs")


class AuditWriter:
    """
    Écrit les AuditEvents en JSON Lines dans un fichier par incident.
    Thread-safe pour un usage synchrone. Pas de lock pour l'async (POC).
    """

    def __init__(self, audit_dir: Path | None = None) -> None:
        self.audit_dir = audit_dir or DEFAULT_AUDIT_DIR
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, incident_id: str) -> Path:
        # Sanitize : éviter les path traversal via l'incident_id
        safe_id = incident_id.replace("/", "_").replace("..", "_")
        return self.audit_dir / f"audit-{safe_id}.jsonl"

    def write(self, event: AuditEvent) -> None:
        """Écrit un événement d'audit. Ne lève jamais d'exception."""
        try:
            path = self._path_for(event.incident_id)
            with path.open("a", encoding="utf-8") as f:
                f.write(event.to_json_line() + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Échec d'écriture de l'audit trail pour incident %s : %s",
                event.incident_id,
                exc,
            )

    def read_all(self, incident_id: str) -> list[AuditEvent]:
        """Relit tous les événements d'un incident (utile pour les tests)."""
        import json

        path = self._path_for(incident_id)
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(AuditEvent(**json.loads(line)))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Ligne d'audit illisible : %s — %s", line[:80], exc)
        return events
