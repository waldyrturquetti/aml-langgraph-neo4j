from aml_alert_triage.config import AppConfig
from aml_alert_triage.llm import InsightResponse
from aml_alert_triage.repository import Neo4jAlertRepository
from aml_alert_triage.sample_data import SAMPLE_ALERTS
from aml_alert_triage.workflow import (
    assess_risk,
    build_triage_response,
    enrich_state,
    finalize_state,
    generate_insights,
    initialize_state,
    review_evidence,
    run_triage,
    should_widen_search,
    widen_search,
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


def _run_full_enrichment(alert, repository, config):
    state = enrich_state(initialize_state(alert), repository)
    while should_widen_search(state, config):
        state = widen_search(state)
        state = enrich_state(state, repository)
    return state


def test_initialize_state_records_alert_metadata() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    state = initialize_state(alert, user_prompt="Explain suspicious links")

    assert state.alert.alert_id == "alert-001"
    assert state.investigation_status == "initialized"
    assert state.metadata["customer_id"] == "cust-100"
    assert state.user_prompt == "Explain suspicious links"
    assert state.hop_radius == 1
    assert state.enrichment_attempts == 0


def test_enrichment_loads_fictional_graph_evidence() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(alert), repository)

    assert state.investigation_status == "enriched"
    assert len(state.evidence) == 5
    assert state.enrichment_attempts == 1
    assert state.workflow_steps[-1] == "enriched-hop-1"


def test_review_generates_structured_recommendation() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(alert), repository)
    state = generate_insights(state, _StaticAdapter())
    recommendation = review_evidence(state)

    assert recommendation.disposition == "review"
    assert recommendation.supporting_evidence
    assert "Factual evidence:" in recommendation.rationale
    assert "Interpretive LLM insights:" in recommendation.rationale


def test_finalize_state_marks_workflow_complete() -> None:
    alert = SAMPLE_ALERTS["alert-002"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(alert), repository)
    state = generate_insights(state, _StaticAdapter())
    final_state = finalize_state(state, review_evidence(state))

    assert final_state.investigation_status == "completed"
    assert final_state.recommendation is not None
    assert final_state.workflow_steps[-1] == "completed"


def test_run_triage_returns_deterministic_structure() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()

    adapter = _StaticAdapter()
    first = run_triage(alert, repository, llm_adapter=adapter, config=config, user_prompt="Focus on connected entities")
    second = run_triage(alert, repository, llm_adapter=adapter, config=config, user_prompt="Focus on connected entities")

    assert first.recommendation is not None
    assert second.recommendation is not None
    assert first.recommendation.disposition == second.recommendation.disposition
    assert first.recommendation.rationale == second.recommendation.rationale
    assert first.workflow_steps == second.workflow_steps


def test_insight_generation_fallback_keeps_workflow_safe() -> None:
    alert = SAMPLE_ALERTS["alert-002"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(alert), repository)

    state = generate_insights(state, _FailingAdapter())
    recommendation = review_evidence(state)
    final_state = finalize_state(state, recommendation)

    assert state.insights.status == "fallback"
    assert state.insights.error is not None
    assert final_state.investigation_status == "completed"


def test_build_triage_response_includes_insight_fields() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = run_triage(alert, repository, llm_adapter=_StaticAdapter(), config=AppConfig(), user_prompt="Summarize the risk")

    payload = build_triage_response(state)

    assert payload["alert_id"] == "alert-001"
    assert payload["workflow_steps"][-1] == "completed"
    assert payload["insights"]["status"] == "generated"
    assert isinstance(payload["insights"]["key_observations"], list)
    assert payload["risk"]["level"] == "elevated"
    assert payload["requires_human_review"] is False
    assert payload["analyst_decision"] is None


# --- Widen-search retry loop -------------------------------------------------


def test_should_widen_search_true_when_evidence_empty_and_budget_remains() -> None:
    alert = SAMPLE_ALERTS["alert-002"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()
    state = enrich_state(initialize_state(alert), repository)

    assert not state.evidence
    assert should_widen_search(state, config) is True


def test_widen_search_increments_hop_radius_and_logs_step() -> None:
    alert = SAMPLE_ALERTS["alert-002"]
    state = initialize_state(alert)

    widened = widen_search(state)

    assert widened.hop_radius == 2
    assert widened.workflow_steps[-1] == "widened-search-radius"


def test_retry_loop_recovers_evidence_at_wider_hop_radius() -> None:
    # cust-500 has exactly one (sparse) transaction at hop 1 - below
    # min_evidence_for_conclusion - so the widen_search cycle pulls in that
    # counterparty's other activity at hop 2.
    alert = SAMPLE_ALERTS["alert-005"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()

    state = _run_full_enrichment(alert, repository, config)

    assert state.hop_radius == 2
    assert state.enrichment_attempts == 2
    assert len(state.evidence) > 1
    assert state.evidence[0].subject == "acct-108"
    assert state.workflow_steps == [
        "initialized",
        "enriched-hop-1",
        "widened-search-radius",
        "enriched-hop-2",
    ]


def test_retry_loop_terminates_when_no_evidence_exists_anywhere() -> None:
    # cust-200 has no evidence at any hop, so the loop must still terminate
    # (bounded by max_enrichment_attempts / neo4j_max_hops) instead of
    # spinning forever looking for evidence that will never appear.
    alert = SAMPLE_ALERTS["alert-002"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()

    state = _run_full_enrichment(alert, repository, config)

    assert not state.evidence
    assert state.enrichment_attempts == config.max_enrichment_attempts
    assert state.hop_radius == config.neo4j_max_hops
    assert should_widen_search(state, config) is False


# --- Risk assessment (cycle / structuring typologies) ------------------------


def test_assess_risk_flags_cycle_as_high_risk() -> None:
    alert = SAMPLE_ALERTS["alert-003"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(alert), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "high"
    assert risk_state.risk.typologies == ["cycle"]
    assert risk_state.requires_human_review is True


def test_assess_risk_flags_structuring_fanout_as_high_risk() -> None:
    alert = SAMPLE_ALERTS["alert-004"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(alert), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "high"
    assert risk_state.risk.typologies == ["structuring-fanout"]
    assert risk_state.requires_human_review is True


def test_assess_risk_flags_structuring_fanin_as_high_risk() -> None:
    alert = SAMPLE_ALERTS["alert-006"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(alert), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "high"
    assert risk_state.risk.typologies == ["structuring-fanin"]
    assert risk_state.requires_human_review is True


def test_assess_risk_is_elevated_for_ordinary_evidence() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(alert), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "elevated"
    assert risk_state.risk.typologies == []
    assert risk_state.requires_human_review is False


def test_assess_risk_is_low_when_no_evidence_after_retries() -> None:
    alert = SAMPLE_ALERTS["alert-002"]
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()
    state = _run_full_enrichment(alert, repository, config)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "low"
    assert risk_state.requires_human_review is False


# --- Human-review escalation path (linear run_triage) ------------------------


def test_run_triage_escalates_high_risk_without_callback() -> None:
    alert = SAMPLE_ALERTS["alert-003"]
    repository = Neo4jAlertRepository.offline(AppConfig())

    state = run_triage(alert, repository, llm_adapter=_StaticAdapter(), config=AppConfig())

    assert state.requires_human_review is True
    assert state.analyst_decision == "pending-manual-review"
    assert state.recommendation.disposition == "escalate"
    assert "analyst-reviewed" in state.workflow_steps


def test_run_triage_confirms_escalation_via_callback() -> None:
    alert = SAMPLE_ALERTS["alert-003"]
    repository = Neo4jAlertRepository.offline(AppConfig())

    state = run_triage(
        alert,
        repository,
        llm_adapter=_StaticAdapter(),
        config=AppConfig(),
        human_review_callback=lambda triage_state: "confirm-escalation",
    )

    assert state.analyst_decision == "confirm-escalation"
    assert state.recommendation.disposition == "escalate"
    assert "confirmed the escalation" in state.recommendation.rationale


def test_run_triage_downgrades_on_analyst_rejection() -> None:
    alert = SAMPLE_ALERTS["alert-004"]
    repository = Neo4jAlertRepository.offline(AppConfig())

    state = run_triage(
        alert,
        repository,
        llm_adapter=_StaticAdapter(),
        config=AppConfig(),
        human_review_callback=lambda triage_state: "reject-escalation",
    )

    assert state.analyst_decision == "reject-escalation"
    assert state.recommendation.disposition == "review"
    assert "downgraded" in state.recommendation.rationale


def test_run_triage_does_not_trigger_review_for_ordinary_evidence() -> None:
    alert = SAMPLE_ALERTS["alert-001"]
    repository = Neo4jAlertRepository.offline(AppConfig())

    state = run_triage(alert, repository, llm_adapter=_StaticAdapter(), config=AppConfig())

    assert state.requires_human_review is False
    assert state.analyst_decision is None
    assert "analyst-reviewed" not in state.workflow_steps
