from aml_alert_triage.config import AppConfig
from aml_alert_triage.repository import Neo4jAlertRepository
from aml_alert_triage.sample_data import SAMPLE_ALERTS
from aml_alert_triage.workflow import enrich_state, finalize_state, initialize_state, review_evidence, run_triage


def test_initialize_state_records_alert_metadata() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    state = initialize_state(alert)

    assert state.alert.alert_id == "alert-001"
    assert state.investigation_status == "initialized"
    assert state.metadata["customer_id"] == "cust-100"


def test_enrichment_loads_fictional_graph_evidence() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository(AppConfig())
    state = enrich_state(initialize_state(alert), repository)

    assert state.investigation_status == "enriched"
    assert len(state.evidence) == 2


def test_review_generates_structured_recommendation() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository(AppConfig())
    state = enrich_state(initialize_state(alert), repository)
    recommendation = review_evidence(state)

    assert recommendation.disposition == "review"
    assert recommendation.supporting_evidence
    assert "graph evidence" in recommendation.rationale


def test_finalize_state_marks_workflow_complete() -> None:
    alert = SAMPLE_ALERTS["alert-002"]
    repository = Neo4jAlertRepository(AppConfig())
    state = enrich_state(initialize_state(alert), repository)
    final_state = finalize_state(state, review_evidence(state))

    assert final_state.investigation_status == "completed"
    assert final_state.recommendation is not None
    assert final_state.workflow_steps[-1] == "completed"


def test_run_triage_returns_deterministic_structure() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository(AppConfig())

    first = run_triage(alert, repository)
    second = run_triage(alert, repository)

    assert first.recommendation is not None
    assert second.recommendation is not None
    assert first.recommendation.disposition == second.recommendation.disposition
    assert first.recommendation.rationale == second.recommendation.rationale
    assert first.workflow_steps == second.workflow_steps
