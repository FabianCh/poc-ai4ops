# syntax=docker/dockerfile:1
# Image de l'agent IA4Ops (FastAPI + LangGraph), construite avec uv.
#   docker build -t ia4ops-agent .
#   docker run --rm -p 8000:8000 ia4ops-agent        # LLM_PROVIDER=mock par défaut

ARG PYTHON_VERSION=3.14

# --- Build : dépendances puis projet dans un virtualenv /app/.venv -------------
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dépendances seules (couche mise en cache tant que uv.lock ne change pas)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Projet (installé en non-editable : le runtime n'a pas besoin des sources)
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# --- Runtime -------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app/audit_logs \
 && chown app:app /app/audit_logs

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LLM_PROVIDER=mock \
    AUDIT_DIR=/app/audit_logs

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

CMD ["uvicorn", "ia4ops_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
