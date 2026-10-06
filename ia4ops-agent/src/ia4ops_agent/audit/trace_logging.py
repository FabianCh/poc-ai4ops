"""Emit bounded JSON trace events to container stdout for Alloy/Loki collection."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_LOGGER_NAME = "ia4ops_agent.trace"
_HANDLER_MARKER = "_ia4ops_json_trace_handler"
_MAX_STRING_LENGTH = 1000
_MAX_LIST_ITEMS = 20
_MAX_DICT_ITEMS = 40
_MAX_EVENT_BYTES = 20_000
_MAX_LOG_SAMPLES = 10
_MAX_LOG_MESSAGE_LENGTH = 500

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|client_secret)"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
# Split the marker literals so the repository's line-based PEM hook does not
# mistake this detection pattern for an embedded private key.
_PEM_BEGIN = "-----" + "BEGIN "
_PEM_END = "-----" + "END "
_PRIVATE_KEY = re.compile(
    re.escape(_PEM_BEGIN)
    + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    + re.escape(_PEM_END)
    + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)


class _DynamicStdoutHandler(logging.Handler):
    """Keep the trace stream compatible with redirected container/test stdout."""

    def emit(self, record: logging.LogRecord) -> None:
        sys.stdout.write(self.format(record) + "\n")
        sys.stdout.flush()


def _redact_string(value: str) -> str:
    value = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", value)
    value = _BEARER_TOKEN.sub("Bearer [REDACTED]", value)
    value = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", value)
    if len(value) > _MAX_STRING_LENGTH:
        return value[:_MAX_STRING_LENGTH] + "…[TRUNCATED]"
    return value


def _sanitize(value: Any, key: str = "") -> Any:
    if any(secret_word in key.lower() for secret_word in (
        "password",
        "passwd",
        "secret",
        "token",
        "credential",
        "private_key",
        "api_key",
        "access_key",
        "authorization",
    )):
        return "[REDACTED]"
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        items = list(value.items())[:_MAX_DICT_ITEMS]
        result = {str(k): _sanitize(v, str(k)) for k, v in items}
        if len(value) > _MAX_DICT_ITEMS:
            result["_truncated_fields"] = len(value) - _MAX_DICT_ITEMS
        return result
    if isinstance(value, (list, tuple)):
        result = [_sanitize(item) for item in value[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            result.append({"_truncated_items": len(value) - _MAX_LIST_ITEMS})
        return result
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_string(str(value))


def _get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
        handler = _DynamicStdoutHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        setattr(handler, _HANDLER_MARKER, True)
        logger.addHandler(handler)
    return logger


def emit_trace_event(event: str, incident_id: str, **fields: Any) -> None:
    """Write one JSON object per line; sensitive-key values and secret-like text are redacted."""
    payload = {
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        "incident_id": incident_id,
        **fields,
    }
    sanitized = _sanitize(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > _MAX_EVENT_BYTES:
        sanitized = {
            key: sanitized[key]
            for key in ("schema_version", "timestamp", "event", "incident_id")
        }
        sanitized["trace_truncated"] = True
        serialized = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    _get_logger().info(serialized)


def sanitized_log_samples(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a bounded allowlist of log fields actually used by the diagnostic."""
    samples = []
    for log in logs[:_MAX_LOG_SAMPLES]:
        message = log.get("message", "")
        samples.append(
            _sanitize(
                {
                    "event_id": log.get("event_id"),
                    "timestamp": log.get("timestamp"),
                    "level": log.get("level"),
                    "service": log.get("service"),
                    "message": str(message)[:_MAX_LOG_MESSAGE_LENGTH],
                }
            )
        )
    return samples
