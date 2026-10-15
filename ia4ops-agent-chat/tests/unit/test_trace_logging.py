import json

from ia4ops_agent.audit.trace_logging import emit_trace_event, sanitized_log_samples


def test_trace_event_is_json_and_redacts_secrets(capsys) -> None:
    emit_trace_event(
        "test_event",
        "inc-test",
        message="Authorization: Bearer abc.def password=hunter2",
        credentials={"client_secret": "do-not-log"},
    )

    event = json.loads(capsys.readouterr().out)
    assert event["schema_version"] == 1
    assert event["event"] == "test_event"
    assert event["incident_id"] == "inc-test"
    assert event["message"] == "Authorization: Bearer [REDACTED] password=[REDACTED]"
    assert event["credentials"] == "[REDACTED]"


def test_trace_event_redacts_key_variants(capsys) -> None:
    emit_trace_event(
        "test_event",
        "inc-test",
        api_key="api-secret",
        access_key="access-secret",
        authorization="raw-auth-value",
    )

    event = json.loads(capsys.readouterr().out)
    assert event["api_key"] == "[REDACTED]"
    assert event["access_key"] == "[REDACTED]"
    assert event["authorization"] == "[REDACTED]"


def test_trace_event_redacts_private_key_material(capsys) -> None:
    begin_marker = "-----" + "BEGIN "
    end_marker = "-----" + "END "
    key_type = "PRIVATE " + "KEY"
    private_key = (
        f"{begin_marker}{key_type}-----\n"
        "test-key-material\n"
        f"{end_marker}{key_type}-----"
    )
    emit_trace_event("test_event", "inc-test", details=private_key)

    event = json.loads(capsys.readouterr().out)
    assert event["details"] == "[REDACTED PRIVATE KEY]"


def test_log_samples_are_bounded_and_allowlisted() -> None:
    logs = [
        {
            "event_id": f"log-{index}",
            "timestamp": "2026-10-06T12:00:00Z",
            "level": "error",
            "service": "checkout",
            "message": "failure token=abc",
            "untrusted_extra": "must not be included",
        }
        for index in range(12)
    ]

    samples = sanitized_log_samples(logs)

    assert len(samples) == 10
    assert samples[0]["message"] == "failure token=[REDACTED]"
    assert "untrusted_extra" not in samples[0]


def test_trace_event_truncates_long_strings(capsys) -> None:
    emit_trace_event("test_event", "inc-test", detail="x" * 1500)

    event = json.loads(capsys.readouterr().out)
    assert event["detail"].endswith("…[TRUNCATED]")
    assert len(event["detail"]) < 1020


def test_trace_event_respects_global_size_limit(capsys) -> None:
    emit_trace_event("test_event", "inc-test", details=["x" * 1000] * 20)

    output = capsys.readouterr().out
    event = json.loads(output)
    assert len(output.encode("utf-8")) <= 20_000
    assert event["trace_truncated"] is True
    assert "details" not in event
