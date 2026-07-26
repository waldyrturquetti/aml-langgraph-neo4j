from aml_alert_triage.config import AppConfig
from aml_alert_triage.llm import InsightResponse
from aml_alert_triage.repository import Neo4jAlertRepository
from aml_alert_triage.sample_data import SAMPLE_ALERTS
from aml_alert_triage.workflow import (
    build_triage_response,
    enrich_state,
    finalize_state,
    generate_insights,
    initialize_state,
    review_evidence,
    run_triage,
)


class _StaticAdapter:
    def generate_insights(self, request):
        return InsightResponse(
            summary="Linked activity suggests moderate escalation risk.",
            key_observations=["Observed repeated linked transactions."],
        )


class _FailingAdapter:
    def generate_insights(self, request):
        raise RuntimeError("provider timeout")


def test_initialize_state_records_alert_metadata() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    state = initialize_state(alert, user_prompt="Explain suspicious links")

    assert state.alert.alert_id == "alert-001"
    assert state.investigation_status == "initialized"
    assert state.metadata["customer_id"] == "cust-100"
    assert state.user_prompt == "Explain suspicious links"


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
    state = generate_insights(state, _StaticAdapter())
    recommendation = review_evidence(state)

    assert recommendation.disposition == "review"
    assert recommendation.supporting_evidence
    assert "Factual evidence:" in recommendation.rationale
    assert "Interpretive LLM insights:" in recommendation.rationale


def test_finalize_state_marks_workflow_complete() -> None:
    alert = SAMPLE_ALERTS["alert-002"]
    repository = Neo4jAlertRepository(AppConfig())
    state = enrich_state(initialize_state(alert), repository)
    state = generate_insights(state, _StaticAdapter())
    final_state = finalize_state(state, review_evidence(state))

    assert final_state.investigation_status == "completed"
    assert final_state.recommendation is not None
    assert final_state.workflow_steps[-1] == "completed"


def test_run_triage_returns_deterministic_structure() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository(AppConfig())

    adapter = _StaticAdapter()
    first = run_triage(alert, repository, llm_adapter=adapter, user_prompt="Focus on connected entities")
    second = run_triage(alert, repository, llm_adapter=adapter, user_prompt="Focus on connected entities")

    assert first.recommendation is not None
    assert second.recommendation is not None
    assert first.recommendation.disposition == second.recommendation.disposition
    assert first.recommendation.rationale == second.recommendation.rationale
    assert first.workflow_steps == second.workflow_steps


def test_insight_generation_fallback_keeps_workflow_safe() -> None:
    alert = SAMPLE_ALERTS["alert-002"]
    repository = Neo4jAlertRepository(AppConfig())
    state = enrich_state(initialize_state(alert), repository)

    state = generate_insights(state, _FailingAdapter())
    recommendation = review_evidence(state)
    final_state = finalize_state(state, recommendation)

    assert state.insights.status == "fallback"
    assert state.insights.error is not None
    assert final_state.investigation_status == "completed"


def test_build_triage_response_includes_insight_fields() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository(AppConfig())
    state = run_triage(alert, repository, llm_adapter=_StaticAdapter(), user_prompt="Summarize the risk")

    payload = build_triage_response(state)

    assert payload["alert_id"] == "alert-001"
    assert payload["workflow_steps"][-1] == "completed"
    assert payload["insights"]["status"] == "generated"
    assert isinstance(payload["insights"]["key_observations"], list)
