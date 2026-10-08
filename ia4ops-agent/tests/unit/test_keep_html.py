"""Tests de la mise en forme HTML des activités Keep."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from ia4ops_agent.integrations.keep_html import (
    _t,
    build_comments,
    build_resolution_comment,
    grafana_logs_url,
    link,
)

ALLOWED_TAGS = {
    "p", "strong", "em", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td", "a",
}  # fmt: skip

HOSTILE = '<script>alert(1)</script><img src=x onerror="alert(2)"> a & b <b>gras</b>'


def _diagnosis(**overrides: object) -> dict[str, object]:
    diagnosis: dict[str, object] = {
        "affected_service": "product-catalog",
        "severity_assessment": "high",
        "summary": "Le taux d'erreur dépasse le seuil.",
        "primary_hypothesis": {
            "title": "Flag productCatalogFailure actif",
            "likelihood": "high",
            "reasoning": "Les erreurs commencent avec l'activation du flag.",
        },
        "evidence": [
            {"source": "logs", "observation": "Error: Fail Feature Flag Enabled (x 214)."},
            {"source": "metrics", "observation": "Taux d'erreur : 10,1 %."},
        ],
        "missing_information": ["État Kubernetes indisponible."],
        "recommended_next_checks": ["Lire l'état du flag.", "Comparer avec Git."],
    }
    diagnosis.update(overrides)
    return diagnosis


def _build(diagnosis: dict[str, object], **kwargs: object) -> list[str]:
    options: dict[str, object] = {
        "agent_incident_id": "agent-inc-1",
        "diagnosis": diagnosis,
        "source_status": {"metrics": "success", "logs": "success", "cluster": "unavailable"},
        "alert_status": "firing",
        "resolved_at": None,
    }
    options.update(kwargs)
    return build_comments(**options)  # type: ignore[arg-type]


def _ms(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1000))


def _tags(html: str) -> set[str]:
    return set(re.findall(r"</?([a-z0-9]+)", html))


def test_builds_three_comments_in_reading_order_each_starting_with_a_paragraph() -> None:
    comments = _build(_diagnosis())

    assert len(comments) == 3
    assert all(comment.startswith("<p>") for comment in comments)
    assert "Résumé du diagnostic" in comments[0]
    assert "<table>" in comments[0]
    assert "<td>product-catalog</td>" in comments[0]
    assert "Hypothèse principale</strong> : Flag productCatalogFailure actif" in comments[1]
    assert (
        "<li><strong>logs</strong> : Error: Fail Feature Flag Enabled (x 214).</li>"
        in comments[1]
    )
    limits = comments[2].replace("&#x27;", "'")
    assert "<ol><li>Lire l'état du flag.</li><li>Comparer avec Git.</li></ol>" in limits
    assert "Kubernetes : unavailable" in limits
    assert "Aucune action de remédiation n'a été exécutée." in limits


def test_only_validated_tags_are_used() -> None:
    links = [("Logs", "https://grafana.example/explore?a=1&b=2")]
    for comment in _build(_diagnosis(), links=links):
        assert _tags(comment) <= ALLOWED_TAGS


def test_dynamic_content_is_escaped_everywhere() -> None:
    diagnosis = _diagnosis(
        affected_service=HOSTILE,
        severity_assessment=HOSTILE,
        summary=HOSTILE,
        primary_hypothesis={"title": HOSTILE, "likelihood": HOSTILE, "reasoning": HOSTILE},
        evidence=[{"source": HOSTILE, "observation": HOSTILE}],
        missing_information=[HOSTILE],
        recommended_next_checks=[HOSTILE],
    )

    comments = _build(diagnosis, agent_incident_id=HOSTILE, source_status={HOSTILE: HOSTILE})

    for comment in comments:
        assert "<script" not in comment
        assert "<img" not in comment
        assert "<b>" not in comment
        assert re.search(r"<[^>]*onerror", comment) is None  # jamais dans une vraie balise
        assert _tags(comment) <= ALLOWED_TAGS
    assert "&lt;script&gt;" in comments[0]
    assert "a &amp; b" in comments[0]


def test_failure_publishes_a_single_clear_comment() -> None:
    diagnosis = {"failure_reason": "Échec <de> validation", "attempts": 3}

    comments = _build(diagnosis)

    assert len(comments) == 1
    assert comments[0].startswith("<p>")
    assert "Diagnostic indisponible" in comments[0]
    assert "3 tentative(s)" in comments[0]
    assert "Échec &lt;de&gt; validation" in comments[0]
    assert "Aucune action de remédiation" in comments[0]


def test_resolved_alert_state_includes_the_resolution_time() -> None:
    comments = _build(_diagnosis(), alert_status="resolved", resolved_at="2026-10-08T10:00:00Z")

    assert "resolved — 2026-10-08T10:00:00Z" in comments[0]


def test_text_is_cut_at_a_word_boundary_with_an_ellipsis() -> None:
    text = _t("un deux trois quatre cinq six sept huit", limit=20)

    assert text.endswith("…")
    assert len(text) <= 20
    assert text == "un deux trois…"
    assert _t("x" * 50, limit=10) == "x" * 9 + "…"


def test_text_normalizes_whitespace_and_uses_fallback() -> None:
    assert _t("a\n\t b   c") == "a b c"
    assert _t("   ", "repli") == "repli"
    assert _t(None, "repli") == "repli"
    assert _t(42, "repli") == "repli"


def test_links_are_limited_to_http_and_https() -> None:
    assert link("ok", "https://grafana.example/x?a=1&b=2") == (
        '<a href="https://grafana.example/x?a=1&amp;b=2">ok</a>'
    )
    assert link("ok", "http://grafana.example") != ""
    assert link("mauvais", "javascript:alert(1)") == ""
    assert link("mauvais", "data:text/html,<script>") == ""
    assert link("mauvais", "//grafana.example") == ""
    comments = _build(
        _diagnosis(),
        links=[("Mauvais", "javascript:alert(1)"), ("Bon", "https://g.example/e")],
    )
    assert "javascript" not in comments[1]
    assert '<a href="https://g.example/e">Bon</a>' in comments[1]


def test_no_code_tag_is_emitted() -> None:
    assert all("<code" not in comment for comment in _build(_diagnosis()))


def test_resolution_comment_is_html_and_escaped() -> None:
    comment = build_resolution_comment("<b>2026</b>")

    assert comment.startswith("<p>")
    assert "<b>" not in comment
    assert "Alerte résolue" in comment
    assert "résolu." in build_resolution_comment(None)


def test_grafana_logs_url_targets_loki_with_the_service_and_time_range() -> None:
    start = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
    end = datetime(2026, 10, 8, 10, 30, tzinfo=UTC)

    url = grafana_logs_url(
        "https://grafana.example/",
        namespace="otel-demo",
        service='prod"uct',
        start=start,
        end=end,
    )

    parsed = urlparse(url)
    assert parsed.path == "/explore"
    pane = json.loads(parse_qs(parsed.query)["panes"][0])["a"]
    expr = pane["queries"][0]["expr"]
    assert expr == '{service_name="prod\\"uct",k8s_namespace_name="otel-demo"}'
    assert pane["datasource"] == "loki"
    assert pane["range"]["from"] == _ms(datetime(2026, 10, 8, 9, 50, tzinfo=UTC))
    assert pane["range"]["to"] == _ms(datetime(2026, 10, 8, 10, 35, tzinfo=UTC))


def test_grafana_logs_url_stays_open_ended_while_the_alert_is_firing() -> None:
    url = grafana_logs_url(
        "https://grafana.example",
        namespace="otel-demo",
        service=None,
        start=datetime(2026, 10, 8, 10, 0, tzinfo=UTC),
    )

    pane = json.loads(parse_qs(urlparse(url).query)["panes"][0])["a"]
    assert pane["range"]["to"] == "now"
    assert pane["queries"][0]["expr"] == '{k8s_namespace_name="otel-demo"}'
