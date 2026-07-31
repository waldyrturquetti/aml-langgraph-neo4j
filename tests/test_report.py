from pathlib import Path

import pytest

from aml_alert_triage.config import AppConfig
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
        reason="cycle-detected",
        description="Directed fund-transfer cycle detected.",
        evidence=[
            EvidenceItem(kind="cycle", subject="cust-200", details="4-hop cycle.", source="neo4j"),
            EvidenceItem(kind="ted", subject="acct-201", details="TED transfer of 100.00 BRL to acct-201.", source="neo4j"),
        ],
        risk=RiskAssessment(level="high", rationale="Structural graph pattern(s) detected: cycle.", typologies=["cycle"]),
        insight_mode=insight_mode,
        insight_summary="A directed cycle was detected returning to the originating account.",
        insight_key_observations=["Cycle spans 4 hops."],
        alert_reason="Cycle detected in transfer graph.",
        created_at="2026-07-30T00:00:00+00:00",
    )


def test_render_alert_report_includes_key_sections() -> None:
    markdown = render_alert_report(_make_snapshot())

    assert "# Alert Investigation Report: alert-auto-cust-200" in markdown
    assert "cust-200" in markdown
    assert "Static (rule-based) analysis" in markdown
    assert "Cycle spans 4 hops." in markdown
    assert "Cycle detected in transfer graph." in markdown
    assert "| cycle | cust-200 | 4-hop cycle. | neo4j |" in markdown
    assert "acct-201" in markdown


def test_render_alert_report_labels_llm_provider() -> None:
    markdown = render_alert_report(_make_snapshot(insight_mode="openai"))

    assert "LLM analysis (provider: openai)" in markdown


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
