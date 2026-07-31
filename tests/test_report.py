from pathlib import Path

import pytest

from aml_alert_triage.models import EvidenceItem, RiskAssessment
from aml_alert_triage.report import generate_alert_report, render_alert_report
from aml_alert_triage.snapshot_store import AlertSnapshot, AlertSnapshotStore


class _FakeSnapshotStore:
    def __init__(self, snapshots: dict[str, AlertSnapshot]) -> None:
        self._snapshots = snapshots

    def get_snapshot(self, alert_id: str) -> AlertSnapshot | None:
        return self._snapshots.get(alert_id)


def _make_snapshot(insight_mode: str = "static") -> AlertSnapshot:
    return AlertSnapshot(
        alert_id="alert-auto-cust-200",
        customer_id="cust-200",
        reason="Padrão(ões) estrutural(is) detectado(s): Ciclo de transferências.",
        description="Foi detectado um ciclo direcionado retornando à conta de origem.",
        evidence=[
            EvidenceItem(
                kind="cycle",
                subject="cust-200",
                details="Detected a directed fund-transfer cycle spanning 4 hop(s) that returns to the originating account.",
                source="neo4j",
            ),
            EvidenceItem(
                kind="ted",
                subject="acct-201",
                details="TED transfer of 100.00 BRL to acct-201.",
                source="neo4j",
            ),
        ],
        risk=RiskAssessment(level="high", rationale="Structural graph pattern(s) detected: cycle.", typologies=["cycle"]),
        insight_mode=insight_mode,
        insight_summary="Foi detectado um ciclo direcionado retornando à conta de origem.",
        insight_key_observations=["O ciclo tem 4 saltos."],
        alert_reason="Padrão(ões) estrutural(is) detectado(s): Ciclo de transferências.",
        created_at="2026-07-30T00:00:00+00:00",
    )


def test_render_alert_report_includes_key_sections_in_portuguese() -> None:
    markdown = render_alert_report(_make_snapshot())

    assert "# Relatório de Investigação de Alerta: alert-auto-cust-200" in markdown
    assert "cust-200" in markdown
    assert "Análise estática (baseada em regras)" in markdown
    assert "O ciclo tem 4 saltos." in markdown
    assert "Padrão(ões) estrutural(is) detectado(s): Ciclo de transferências." in markdown
    assert "Ciclo de transferências" in markdown  # translated risk typology label


def test_render_alert_report_translates_evidence_details() -> None:
    markdown = render_alert_report(_make_snapshot())

    # Cycle evidence, translated from the fixed English template.
    assert "Detectado um ciclo direcionado de transferências com 4 salto(s)" in markdown
    # Transaction evidence, translated from format_transaction_details' template.
    assert "Transferência TED de 100.00 BRL para acct-201." in markdown
    # Original English text should not leak into the rendered table.
    assert "Detected a directed fund-transfer cycle" not in markdown
    assert "TED transfer of 100.00 BRL to acct-201." not in markdown


def test_render_alert_report_translates_risk_rationale() -> None:
    markdown = render_alert_report(_make_snapshot())

    assert "Padrão(ões) estrutural(is) detectado(s): Ciclo de transferências." in markdown


def test_render_alert_report_labels_llm_provider() -> None:
    markdown = render_alert_report(_make_snapshot(insight_mode="openai"))

    assert "Análise via LLM (provedor: openai)" in markdown


def test_render_alert_report_includes_cypher_visualization_query() -> None:
    markdown = render_alert_report(_make_snapshot())

    assert "```cypher" in markdown
    assert "MATCH (c:Customer {customer_id: 'cust-200'})-[:OWNS]->(acct)" in markdown
    assert "TRANSFERRED_TO*1..3" in markdown
    assert "MATCH (a:Alert {alert_id: 'alert-auto-cust-200'})-[:TARGETS]->(c:Customer) RETURN a, c;" in markdown


def test_generate_alert_report_writes_file(tmp_path: Path) -> None:
    snapshot = _make_snapshot()
    store = _FakeSnapshotStore({snapshot.alert_id: snapshot})
    output_path = tmp_path / "custom" / "report.md"

    result_path = generate_alert_report(snapshot.alert_id, store, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert "cust-200" in output_path.read_text(encoding="utf-8")


def test_generate_alert_report_defaults_to_reports_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    snapshot = _make_snapshot()
    store = _FakeSnapshotStore({snapshot.alert_id: snapshot})

    result_path = generate_alert_report(snapshot.alert_id, store)

    assert result_path == Path("reports") / f"{snapshot.alert_id}.md"
    assert result_path.exists()


def test_generate_alert_report_raises_clear_error_when_missing() -> None:
    store = _FakeSnapshotStore({})

    with pytest.raises(RuntimeError, match="No snapshot found"):
        generate_alert_report("does-not-exist", store)
