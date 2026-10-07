"""
Configuration de l'application via pydantic-settings.

Toutes les variables sont lues depuis l'environnement ou un fichier .env.
Les valeurs par défaut correspondent à un environnement de développement local.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuration principale de l'agent IA4Ops.

    Variables prioritaires :
    - LLM_PROVIDER          : "mock" (dev) ou "gemini" (prod)
    - DATA_PROVIDER         : "mock" ou "real" pour les providers de données
    - GOOGLE_APPLICATION_CREDENTIALS : chemin vers le service account JSON (prod)
    - GOOGLE_CLOUD_PROJECT  : projet GCP (prod)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- API ---
    app_name: str = "ia4ops-agent"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000

    # --- LLM ---
    # "mock" → FakeLLMClient, "gemini" → GeminiVertexClient
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    data_provider: str = Field(default="mock", alias="DATA_PROVIDER")
    # Nom du modèle Vertex AI — configurable sans toucher au code
    vertex_model: str = Field(default="gemini-2.0-flash", alias="LLM_MODEL")

    # --- Vertex AI (Task 6) ---
    google_application_credentials: str | None = Field(
        default=None,
        alias="GOOGLE_APPLICATION_CREDENTIALS",
    )
    google_cloud_project: str | None = Field(
        default=None,
        alias="GOOGLE_CLOUD_PROJECT",
    )
    # Accepte VERTEX_AI_LOCATION ou GOOGLE_CLOUD_LOCATION (les deux sont équivalents)
    vertex_ai_location: str = Field(
        default="europe-west1",
        alias="VERTEX_AI_LOCATION",
    )
    google_cloud_location: str = Field(
        default="europe-west1",
        alias="GOOGLE_CLOUD_LOCATION",
    )

    @property
    def effective_location(self) -> str:
        """Retourne la région effective — préfère VERTEX_AI_LOCATION si défini."""
        return self.vertex_ai_location or self.google_cloud_location

    # --- Grafana API proxy (Task 8) ---
    grafana_base_url: str | None = Field(
        default=None,
        alias="GRAFANA_BASE_URL",
    )
    grafana_username: str = Field(default="admin", alias="GRAFANA_USERNAME")
    grafana_password: str | None = Field(default=None, alias="GRAFANA_PASSWORD")

    # --- OTel Demo (Task 8) ---
    otel_demo_base_url: str | None = Field(
        default=None,
        alias="OTEL_DEMO_BASE_URL",
    )

    # --- Audit trail ---
    audit_dir: Path = Field(default=Path("audit_logs"), alias="AUDIT_DIR")

    # --- Déduplication ---
    # Taille maximale du cache de déduplication en mémoire
    dedup_cache_max_size: int = 1000


# Instance unique partagée dans toute l'application
settings = Settings()
