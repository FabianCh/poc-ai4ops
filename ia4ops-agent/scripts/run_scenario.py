"""
Script de démonstration locale — exécute un scénario de bout en bout.

Usage :
    uv run python scripts/run_scenario.py case_a
    uv run python scripts/run_scenario.py case_b
    uv run python scripts/run_scenario.py case_c

Le script charge la fixture JSON correspondante, exécute le graphe LangGraph
avec les providers mockés et le FakeLLMClient, puis affiche le rapport complet.
"""

import asyncio
import json
import sys
from pathlib import Path

# Résoudre le chemin src/ pour les imports
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


FIXTURES = {
    "case_a": _ROOT / "tests/fixtures/alerts/case_a_dependency_timeout.json",
    "case_b": _ROOT / "tests/fixtures/alerts/case_b_unstable_pod.json",
    "case_c": _ROOT / "tests/fixtures/alerts/case_c_insufficient_data.json",
}

AUDIT_DIR = _ROOT / "audit_logs"


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def green(t: str) -> str: return _color(t, "32")
def yellow(t: str) -> str: return _color(t, "33")
def red(t: str) -> str: return _color(t, "31")
def bold(t: str) -> str: return _color(t, "1")
def cyan(t: str) -> str: return _color(t, "36")


def print_separator(char: str = "─", width: int = 70) -> None:
    print(char * width)


def print_report(state: dict) -> None:
    report = state.get("report", {})
    diagnosis = report.get("diagnosis", {})
    incident_id = state.get("incident_id", "unknown")

    print()
    print_separator("═")
    print(bold(f"  RAPPORT DE DIAGNOSTIC — {incident_id}"))
    print_separator("═")

    # Statut global
    status = report.get("status", "unknown")
    status_display = green(status) if "error" not in status else yellow(status)
    print(f"\n  Statut       : {status_display}")
    print(f"  Finalisé le  : {report.get('finalized_at', 'n/a')}")
    print(f"  Action exécutée : {red('OUI ⚠') if report.get('action_executed') else green('NON ✓')}")

    # Statuts des sources
    print(f"\n{bold('  Sources de données :')}")
    src = report.get("source_status", {})
    for name, sts in src.items():
        icon = green("✓") if sts == "success" else yellow("~") if sts == "partial" else red("✗")
        print(f"    {icon}  {name:<10} → {sts}")

    # Diagnostic
    if diagnosis:
        print(f"\n{bold('  Diagnostic :')}")
        print(f"    Service affecté   : {cyan(diagnosis.get('affected_service', 'n/a'))}")
        sev = diagnosis.get("severity_assessment", "unknown")
        sev_display = red(sev) if sev in ("critical", "high") else yellow(sev) if sev == "medium" else sev
        print(f"    Sévérité          : {sev_display}")
        print("\n    Résumé :")
        for line in (diagnosis.get("summary") or "").split(". "):
            if line.strip():
                print(f"      {line.strip()}.")

        hyp = diagnosis.get("primary_hypothesis", {})
        if hyp:
            print(f"\n    Hypothèse principale ({hyp.get('likelihood', '?')}) :")
            print(f"      {bold(hyp.get('title', ''))}")
            print(f"      {hyp.get('reasoning', '')[:200]}")

        evidence = diagnosis.get("evidence", [])
        if evidence:
            print(f"\n    Preuves ({len(evidence)}) :")
            for ev in evidence:
                print(f"      [{ev['source']}] {ev['reference']} — {ev['observation'][:80]}")

        missing = diagnosis.get("missing_information", [])
        if missing:
            print(f"\n    {yellow('Informations manquantes :')}")
            for m in missing:
                print(f"      ⚠  {m}")

        checks = diagnosis.get("recommended_next_checks", [])
        if checks:
            print("\n    Prochaines vérifications :")
            for c in checks:
                print(f"      →  {c}")

    # Warnings
    warnings = report.get("warnings", [])
    if warnings:
        print(f"\n  {yellow('Avertissements :')}")
        for w in warnings:
            print(f"    ⚠  {w}")

    # Audit trail
    audit_events = state.get("audit_events", [])
    print(f"\n{bold('  Audit trail')} ({len(audit_events)} événements) :")
    for evt in audit_events:
        icon = green("✓") if evt["status"] == "success" else yellow("~") if evt["status"] == "partial" else red("✗") if evt["status"] in ("error", "unavailable", "invalid") else "·"
        duration = f"{evt.get('duration_ms', '?')}ms" if evt.get("duration_ms") is not None else ""
        err = f"  ← {red(evt['error'][:60])}" if evt.get("error") else ""
        print(f"    {icon}  {evt['step']:<20} {duration:<8}{err}")

    # Fichier d'audit
    audit_file = AUDIT_DIR / f"audit-{incident_id}.jsonl"
    if audit_file.exists():
        print(f"\n  Audit écrit : {cyan(str(audit_file))}")

    print()
    print_separator("═")
    print()


async def run(case: str) -> None:
    from ia4ops_agent.graph.builder import build_graph
    from ia4ops_agent.providers.factory import Providers

    fixture_path = FIXTURES.get(case)
    if fixture_path is None:
        print(red(f"Scénario inconnu : '{case}'. Valeurs valides : {', '.join(FIXTURES)}"))
        sys.exit(1)

    if not fixture_path.exists():
        print(red(f"Fixture introuvable : {fixture_path}"))
        sys.exit(1)

    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    # Retirer les clés internes (_mock_scenario, _description)
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}

    print(f"\n{bold('Scénario')} : {cyan(case)}")
    print(f"Fixture  : {fixture_path.name}")
    service = payload["alerts"][0]["labels"].get("service_name", "?")
    print(f"Service  : {cyan(service)}")
    print("\nExécution du graphe LangGraph...")

    AUDIT_DIR.mkdir(exist_ok=True)
    graph = build_graph(providers=Providers.mock(), audit_dir=AUDIT_DIR)
    state = await graph.ainvoke({"raw_alert": payload})

    print_report(state)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : uv run python scripts/run_scenario.py [case_a|case_b|case_c]")
        sys.exit(1)

    asyncio.run(run(sys.argv[1]))
